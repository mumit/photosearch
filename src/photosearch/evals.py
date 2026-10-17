"""`photosearch eval`: does a change to the index change what searches find, and is the result better or worse?

A run compares two variants of the index on a random sample of it, over a fixed set of searches. It measures how
much their results agree, and makes one blind sheet per search (both variants' top photos, as rows X and Y in random
order) for a person or an agent to judge. The report then says which variant's photos fit the searches better.

  photosearch eval run tokens70 tokens=70        re-embed the sample at 70 vision tokens; compare with the index
  photosearch eval run short dims=256            the index's vectors cut to their first 256 numbers
  photosearch eval run binary bits=1             the index's vectors stored as 1 bit per number
  photosearch eval run other index=data-other    another index of the same library
  photosearch eval score tokens70 7 --x 1,2,4 --y 1,3 --first x
  photosearch eval report tokens70

Everything is written to eval/<name>/ in the data folder: run.json, sheets/, judgments.json and report.md.
"""
import json, random, sqlite3, sys, time
from pathlib import Path

import numpy as np

from . import embed
from .config import DATA, THUMBS
from .store import db

EVALS = DATA / "eval"
QUERIES = Path(__file__).with_name("eval_queries.txt")
TOP = 24  # results kept per search: one page


def sample(con, n, seed):
    """The same random photos for the same index and seed. Only photos whose local preview is still on disk, so a
    variant can embed them again."""
    rows = [r for r in con.execute("select uuid, src, vec from photos") if r[1] and Path(r[1]).exists()]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def unit(M):
    return (M / np.linalg.norm(M, axis=-1, keepdims=True)).astype(np.float32)


def embed_images(paths, tokens, batch=16):
    """Vectors for these images at `tokens` vision tokens, and the seconds the model took."""
    from .images import open_image
    m = embed.model()
    embed.set_vision_tokens(m, tokens)
    vecs, secs = [], 0.0
    try:
        for i in range(0, len(paths), batch):
            ims = [open_image(p) for p in paths[i:i + batch]]
            t = time.time()
            vecs.append(m.encode([{"image": im} for im in ims], batch_size=len(ims), normalize_embeddings=True))
            secs += time.time() - t
            print(f"\r  {tokens} tokens: {i + len(ims)}/{len(paths)}", end="", flush=True)
    finally:
        embed.set_vision_tokens(m, embed.VISION_TOKENS)
    print()
    return np.concatenate(vecs).astype(np.float32), secs


def variant(spec, rows, con, speed):
    """(photo vectors, how a query vector changes to match them, notes) for a variant such as "tokens=70"."""
    kind, _, arg = spec.partition("=")
    base = np.stack([np.frombuffer(r[2], np.float32) for r in rows])
    same = lambda q: q
    if kind == "index" and not arg:
        return base, same, {}
    if kind == "index":
        other = Path(arg) / "index.sqlite"
        if not other.exists():
            sys.exit(f"no index at {other}")
        o = sqlite3.connect(f"file:{other}?mode=ro", uri=True)
        vec = {u: v for u, v in o.execute("select uuid, vec from photos")}
        missing = [r[0] for r in rows if r[0] not in vec]
        if missing:
            sys.exit(f"{len(missing)} of the sample's photos aren't in {other}; index them there first")
        return np.stack([np.frombuffer(vec[r[0]], np.float32) for r in rows]), same, {}
    if kind == "tokens":
        n = int(arg)
        M, secs = embed_images([r[1] for r in rows], n)
        notes = {"photos_per_s": round(len(rows) / secs, 2)}
        if speed:  # the same photos at the index's own setting, for a fair comparison of speed
            have = int(dict(con.execute("select key, value from meta")).get("vision_tokens", embed.VISION_TOKENS))
            again, secs = embed_images([r[1] for r in rows[:speed]], have)
            notes |= {"speed_sample": speed, f"photos_per_s_at_{have}": round(speed / secs, 2),
                      f"photos_per_s_at_{n}": round(speed / embed_images([r[1] for r in rows[:speed]], n)[1], 2),
                      "index_reproduced_cos": round(float((again * base[:speed]).sum(1).mean()), 4)}
        return M, same, notes
    if kind == "dims":
        n = int(arg)
        return unit(base[:, :n]), lambda q: unit(q[:n]), {}
    if kind == "bits" and arg == "1":  # the sign of each number; the query stays as it is
        return np.sign(base).astype(np.float32) / np.sqrt(base.shape[1]), same, {}
    if kind == "bits" and arg == "8":  # each number rounded to one of 255 steps of its vector's largest
        scale = np.abs(base).max(1, keepdims=True) / 127
        return unit(np.round(base / scale) * scale), same, {}
    sys.exit(f"don't know the variant {spec!r}: use index, index=PATH, tokens=N, dims=N, bits=1 or bits=8")


def agreement(a, b):
    """How alike two rankings (indexes into the sample, best first) are."""
    pos = np.empty(len(b), int); pos[b] = np.arange(len(b))
    return dict(first_same=bool(a[0] == b[0]), a_first_rank_in_b=int(pos[a[0]]) + 1,
                overlap10=len(set(a[:10]) & set(b[:10])), overlap24=len(set(a[:TOP]) & set(b[:TOP])))


def run(name, b, a="index", n=2000, seed=7, k=5, queries=None, speed=0):
    out = EVALS / name
    if (out / "judgments.json").exists():
        sys.exit(f"{out} has been judged already; pick another name")
    con = db()
    rows = sample(con, n, seed)
    if not rows:
        sys.exit("the index has no photos whose preview is on disk")
    qs = [q.strip() for q in Path(queries or QUERIES).read_text().splitlines() if q.strip()]
    (MA, qa, na), (MB, qb, nb) = variant(a, rows, con, speed), variant(b, rows, con, speed)
    rng, per = random.Random(seed + 1), []
    for q in qs:
        v = embed.embed_query(q)
        ra, rb = np.argsort(-(MA @ qa(v))), np.argsort(-(MB @ qb(v)))
        per.append(dict(q=q, A=[rows[i][0] for i in ra[:TOP]], B=[rows[i][0] for i in rb[:TOP]], x=rng.choice("AB"),
                        **agreement(ra, rb)))
    summary = dict(searches=len(per), first_same=sum(p["first_same"] for p in per),
                   a_first_in_b_top5=sum(p["a_first_rank_in_b"] <= 5 for p in per),
                   overlap10=round(sum(p["overlap10"] for p in per) / len(per), 2),
                   overlap24=round(sum(p["overlap24"] for p in per) / len(per), 2))
    if MA.shape == MB.shape:
        cos = (MA * MB).sum(1)
        summary["cos"] = dict(mean=round(float(cos.mean()), 4), p5=round(float(np.percentile(cos, 5)), 4),
                              min=round(float(cos.min()), 4))
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(con.execute("select key, value from meta"))
    (out / "run.json").write_text(json.dumps(dict(a=a, b=b, photos=len(rows), seed=seed, k=k, index=meta, notes={a: na, b: nb},
                                                  summary=summary, searches=per), indent=1))
    sheets(out, per, k)
    print(report(name))


def sheets(out, per, k, cell=220):
    """One JPEG per search: row X and row Y, each that variant's top k numbered 1..k. Which is which is in run.json."""
    from PIL import Image, ImageDraw, ImageFont
    d = out / "sheets"; d.mkdir(exist_ok=True)
    font, small = ImageFont.load_default(size=24), ImageFont.load_default(size=18)
    for i, p in enumerate(per, 1):
        sheet = Image.new("RGB", (50 + k * (cell + 6), 44 + 2 * (cell + 6)), "white")
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 8), f"{i}. {p['q']}", fill="black", font=font)
        for r, row in enumerate("XY"):
            y = 44 + r * (cell + 6)
            draw.text((14, y + cell // 2 - 12), row, fill="black", font=font)
            side = p["x"] if row == "X" else "AB".replace(p["x"], "")
            for c, u in enumerate(p[side][:k]):
                x = 50 + c * (cell + 6)
                im = Image.open(THUMBS / f"{u}.jpg"); im.thumbnail((cell, cell))
                sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
                draw.rectangle((x, y, x + 26, y + 24), fill="black")
                draw.text((x + 7, y + 2), str(c + 1), fill="white", font=small)
        sheet.save(d / f"{i:02d}.jpg", quality=80)


def load(name):
    out = EVALS / name
    if not (out / "run.json").exists():
        sys.exit(f"no eval called {name!r}; start one with `photosearch eval run {name} VARIANT`")
    run_ = json.loads((out / "run.json").read_text())
    j = out / "judgments.json"
    return out, run_, json.loads(j.read_text()) if j.exists() else {}


def positions(s, k):
    got = sorted({int(x) for x in s.split(",") if x.strip()}) if s else []
    if any(not 1 <= x <= k for x in got):
        sys.exit(f"photo numbers go from 1 to {k}")
    return got


def score(name, n, x="", y="", first="same", judge="me"):
    """Record which of sheet n's photos fit its search, in each row, and which row's first photo fits better."""
    out, run_, judged = load(name)
    if not 1 <= n <= len(run_["searches"]):
        sys.exit(f"sheets go from 1 to {len(run_['searches'])}")
    if first not in ("x", "y", "same"):
        sys.exit("--first is x, y or same")
    judged.setdefault(judge, {})[str(n)] = dict(x=positions(x, run_["k"]), y=positions(y, run_["k"]), first=first)
    (out / "judgments.json").write_text(json.dumps(judged, indent=1))
    left = [i for i in range(1, len(run_["searches"]) + 1) if str(i) not in judged[judge]]
    print(f"sheet {n} scored; {len(left)} to go" + (f", next: {out / 'sheets' / f'{left[0]:02d}.jpg'}" if left else ""))


def report(name):
    """What the run found, unblinded, as Markdown. Also written to report.md."""
    out, run_, judged = load(name)
    a, b, s, per, k = run_["a"], run_["b"], run_["summary"], run_["searches"], run_["k"]
    lines = [f"# {name}: {a} vs {b}", "",
             f"{run_['photos']} random photos (seed {run_['seed']}), {s['searches']} searches.", "",
             f"| {a} vs {b} | Result |", "|---|---|",
             f"| Same photo first | {s['first_same']} of {s['searches']} searches |",
             f"| {a}'s first photo in {b}'s top 5 | {s['a_first_in_b_top5']} of {s['searches']} |",
             f"| Top 10 in common | {s['overlap10']} on average |",
             f"| First {TOP} in common | {s['overlap24']} on average |"]
    if "cos" in s:
        c = s["cos"]
        lines.append(f"| Cosine between their vectors | {c['mean']} on average (5% below {c['p5']}, lowest {c['min']}) |")
    for spec, notes in run_["notes"].items():
        if notes:
            lines.append(f"| {spec} | " + ", ".join(f"{key}: {v}" for key, v in notes.items()) + " |")
    for judge, scores in judged.items():
        fit, better, differ = {"A": 0, "B": 0}, {"A": 0, "B": 0, "same": 0}, 0
        for n, sc in scores.items():
            p = per[int(n) - 1]
            side = {"x": p["x"], "y": "AB".replace(p["x"], ""), "same": "same"}
            for row in "xy":
                fit[side[row]] += len(sc[row])
            if not p["first_same"]:
                differ += 1
                better[side[sc["first"]]] += 1
        lines += ["", f"Judged blind by {judge}: {len(scores)} of {len(per)} searches.", "",
                  f"| | {a} | {b} |", "|---|---|---|",
                  f"| Top-{k} photos that fit the search (of {len(scores) * k}) | {fit['A']} | {fit['B']} |",
                  f"| Better first photo, of the {differ} searches where it differs | {better['A']} | {better['B']} |",
                  f"| About as good | {better['same']} | |"]
    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text)
    return text


def cmd_eval(a):
    if a.what == "run":
        run(a.name, a.b, a.a, a.photos, a.seed, a.k, a.queries, a.speed)
    elif a.what == "score":
        score(a.name, a.n, a.x, a.y, a.first, a.judge)
    else:
        print(report(a.name), end="")
