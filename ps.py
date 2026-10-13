"""photosearch — semantic search over an Apple Photos library with EmbeddingGemma 2.

  ps.py index  [--limit N] [--library PATH]   embed photos (incremental; safe to re-run)
  ps.py search "kids on a slide" [-k 24] [--person NAME] [--after 2020-01-01] [--before ...]
  ps.py similar UUID [-k 24]                  photos that look like this one
  ps.py serve  [--port 8765]                  local web UI: search, galaxy, time machine, games, photo math
  ps.py album "Name" "query" [-k 50]          put the results into a Photos album

Nothing is downloaded from iCloud: with "Optimize Mac Storage" on we embed the
local preview Photos keeps (the model only sees ~280 visual tokens anyway).
"""
import argparse, functools, io, json, os, random, re, sqlite3, sys, time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DB = DATA / "index.sqlite"
THUMBS = DATA / "thumbs"
MODEL = "google/embeddinggemma-2"
DIM = 768
THUMB_PX = 360
LIBRARY = Path.home() / "Pictures" / "Photos Library.photoslibrary"  # fallback if the system library can't be found


# ---------------------------------------------------------------- storage

def db():
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("pragma journal_mode=wal")  # lets `serve` read while `index` writes
    con.execute("""create table if not exists photos(
        uuid text primary key, date text, kind text, title text, place text,
        persons text, albums text, labels text, src text, vec blob)""")
    cols = {r[1] for r in con.execute("pragma table_info(photos)")}
    for c in ("lat", "lon"):
        if c not in cols:
            con.execute(f"alter table photos add column {c} real")
    con.execute("create table if not exists meta(key text primary key, value text)")
    return con


def check_settings(con):
    """Vectors from different models or vision-token budgets don't mix, so pin them on first index."""
    have = dict(con.execute("select key, value from meta"))
    for k, v in (("model", MODEL), ("vision_tokens", str(VISION_TOKENS))):
        if k in have and have[k] != v:
            sys.exit(f"index was built with {k}={have[k]}, not {v}; use that, or delete data/ and re-index")
        con.execute("insert or ignore into meta values(?,?)", (k, v))
    con.commit()


def load_matrix(con, where="", params=()):
    rows = con.execute(f"select uuid, vec from photos {where}", params).fetchall()
    if not rows:
        return [], np.zeros((0, DIM), np.float32)
    return [r[0] for r in rows], np.stack([np.frombuffer(r[1], np.float32) for r in rows])


_vecs = (None, [], np.zeros((0, DIM), np.float32), {})

def vectors(con):
    """All vectors, held in memory and reloaded only when the index changes (e.g. while `index` runs)."""
    global _vecs
    stamp = con.execute("select count(*), max(rowid) from photos").fetchone()
    if _vecs[0] != stamp:
        uuids, M = load_matrix(con)
        _vecs = (stamp, uuids, M, {u: i for i, u in enumerate(uuids)})
    return _vecs[1:]


def photos_db(library=None):
    import osxphotos
    if library:
        return osxphotos.PhotosDB(dbfile=library)
    try:
        return osxphotos.PhotosDB()
    except FileNotFoundError:  # osxphotos can't always read which library is the system one
        return osxphotos.PhotosDB(dbfile=str(LIBRARY))


# ---------------------------------------------------------------- model

_model = None
VISION_TOKENS = 280  # model default; 70 is ~4x faster at some quality cost (70-1120 supported)

def model():
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        # bf16 is safe for this model; float16 is not (per model card). Audio encoder not needed.
        _model = SentenceTransformer(MODEL, device=dev, config_kwargs={"audio_config": None},
                                     model_kwargs={"torch_dtype": torch.bfloat16 if dev == "mps" else torch.float32})
        proc = _model[0].processor
        proc.image_seq_length = proc.image_processor.image_seq_length = VISION_TOKENS
        proc.image_processor.max_soft_tokens = VISION_TOKENS
    return _model


@functools.lru_cache(maxsize=512)
def embed_query(text):
    return model().encode([text], prompt_name="SearchQuery", normalize_embeddings=True)[0].astype(np.float32)


# ---------------------------------------------------------------- indexing

def best_local_image(p):
    """Largest on-disk preview (fast to decode; for videos it's the poster frame), else a local original."""
    ders = [d for d in (p.path_derivatives or []) if Path(d).exists()]
    if ders:
        return ders[0]  # osxphotos returns largest first
    if p.isphoto and p.path and Path(p.path).exists():
        return p.path
    return None


def open_image(path):
    from PIL import Image, ImageOps
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((1024, 1024))
    return im


def meta(p):
    """Everything we keep about a photo except its vector: cheap to recompute, so refreshed on every index run."""
    lat, lon = p.location or (None, None)
    return (p.date.isoformat(), "video" if p.ismovie else "photo", p.title or "",
            (p.place.name if p.place else "") or "",
            json.dumps(list(dict.fromkeys(x for x in p.persons if x != "_UNKNOWN_"))), json.dumps(p.albums),
            json.dumps(p.labels), lat, lon)


META_COLS = "date, kind, title, place, persons, albums, labels, lat, lon"


def cmd_index(a):
    con = db()
    check_settings(con)
    THUMBS.mkdir(parents=True, exist_ok=True)
    done = {r[0] for r in con.execute("select uuid from photos")}
    print("opening Photos library…", flush=True)
    pdb = photos_db(a.library)
    print(f"library: {pdb.library_path}")
    lib = {p.uuid: p for p in pdb.photos(intrash=False)}
    if lib:  # never prune against an empty read
        gone = done - lib.keys()
        for u in gone:
            con.execute("delete from photos where uuid=?", (u,))
            (THUMBS / f"{u}.jpg").unlink(missing_ok=True)
        keep = done & lib.keys()
        con.executemany(f"update photos set ({META_COLS}) = ({','.join('?' * 9)}) where uuid=?",
                        [meta(lib[u]) + (u,) for u in keep])
        con.commit()
        print(f"refreshed {len(keep)}, removed {len(gone)} deleted from the library")
        done = keep
    todo = [p for u, p in lib.items() if u not in done]
    todo.sort(key=lambda p: p.date, reverse=True)
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(done)} already indexed, {len(todo)} to go (vision tokens: {VISION_TOKENS})")
    m = model()
    t0, n, skipped, batch = time.time(), 0, 0, []

    def flush():
        nonlocal n
        if not batch:
            return
        vecs = m.encode([{"image": im} for _, im, _ in batch], batch_size=len(batch),
                        normalize_embeddings=True).astype(np.float32)
        for (p, im, src), v in zip(batch, vecs):
            th = im.copy(); th.thumbnail((THUMB_PX, THUMB_PX))
            th.save(THUMBS / f"{p.uuid}.jpg", quality=80)
            con.execute(f"insert or replace into photos (uuid, {META_COLS}, src, vec) values ({','.join('?' * 12)})",
                        (p.uuid, *meta(p), src, v.tobytes()))
        con.commit()
        n += len(batch); batch.clear()
        rate = n / (time.time() - t0)
        print(f"\r{n}/{len(todo)}  {rate:.1f}/s  eta {(len(todo)-n)/max(rate,1e-9)/60:.0f} min  skipped {skipped}   ",
              end="", flush=True)

    for p in todo:
        src = best_local_image(p)
        if not src:
            skipped += 1; continue
        try:
            batch.append((p, open_image(src), src))
        except Exception as ex:
            skipped += 1; print(f"\n  skip {p.uuid} ({ex.__class__.__name__}: {ex})"); continue
        if len(batch) >= a.batch:
            flush()
    flush()
    print(f"\ndone: {n} embedded, {skipped} skipped (no local preview / unreadable) in {(time.time()-t0)/60:.1f} min")


# ---------------------------------------------------------------- search

def filtered(con, person=None, after=None, before=None, kind=None, place=None, months=None):
    """person: a name or a list of names (all must be in the photo); names and place match on substrings.
    months: month numbers to keep, e.g. (6, 7, 8) for summer."""
    clauses, params = [], []
    for name in [person] if isinstance(person, str) else person or []:
        clauses.append("exists (select 1 from json_each(persons) where lower(value) like ?)"); params.append(f"%{name.lower()}%")
    if place:
        clauses.append("lower(place) like ?"); params.append(f"%{place.lower()}%")
    if months:
        clauses.append(f"cast(substr(date,6,2) as integer) in ({','.join('?' * len(months))})"); params.extend(months)
    if after:
        clauses.append("date >= ?"); params.append(after)
    if before:
        clauses.append("date < ?"); params.append(before)
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    uuids, M, pos = vectors(con)
    if not clauses:
        return uuids, M
    keep = [r[0] for r in con.execute("select uuid from photos where " + " and ".join(clauses), params)]
    keep = [u for u in keep if u in pos]
    return keep, M[[pos[u] for u in keep]]


def rank(con, qvec, k, **filters):
    uuids, M = filtered(con, **filters)
    if not uuids:
        return []
    scores = M @ qvec
    top = np.argsort(-scores)[:k]
    info = photo_info(con, [uuids[i] for i in top])
    return [dict(info[uuids[i]], score=float(scores[i])) for i in top]


def photo_info(con, uuids):
    rows = con.execute(f"select uuid, date, kind, place, persons, lat, lon from photos where uuid in "
                       f"({','.join('?' * len(uuids))})", list(uuids))
    return {r[0]: dict(uuid=r[0], date=r[1][:10], kind=r[2], place=r[3], persons=json.loads(r[4]), lat=r[5], lon=r[6])
            for r in rows}


def vec_of(con, uuid):
    row = con.execute("select vec from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(f"{uuid} not indexed")
    return np.frombuffer(row[0], np.float32)


EXCLUDE_W = 0.5  # how hard `exclude` pushes away; tested on "group photos at a party" minus "a selfie"

def search(con, query, k=24, exclude=None, **f):
    """exclude: what the photos should NOT show ("a selfie", or a list). The model is weak at negation inside the
    query ("no selfies"), so each is subtracted from the query vector instead, as in photo_math."""
    q = embed_query(query)
    for x in [exclude] if isinstance(exclude, str) else exclude or []:
        q = q - EXCLUDE_W * embed_query(x)
    if exclude:
        q = (q / np.linalg.norm(q)).astype(np.float32)
    return rank(con, q, k, **f)


# ---------------------------------------------------------------- smart search box (optional: TypeSafe Jev)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
# Cut-offs picked on 20 labelled queries, then checked on 20 fresh ones (95/100 answers right).
NO_PEOPLE_P, NO_SELFIES_P, CHOICE_P = 0.7, 0.85, 0.6
SEASONS = {"spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11), "winter": (12, 1, 2)}
JEV_QUESTIONS = {
    "kind": {"type": "choice", "instructions": "Does the user want photos, videos, or either?",
             "criteria": {"photo": "explicitly asks for photos/pictures only", "video": "asks for videos, clips or footage",
                          "either": "doesn't say"}},
    "season": {"type": "choice", "instructions": "Which season of the year does the search mention?",
               "criteria": {"none": "no season mentioned", "spring": "spring", "summer": "summer", "autumn": "fall or autumn",
                            "winter": "winter"}},
    "when": {"type": "choice", "instructions": "What time period does the search ask for?",
             "criteria": {"any": "no time period", "this year": "this year", "last year": "last year",
                          "a named year": "a specific year like 2019",
                          "recent": "recently, lately, the last few weeks or months",
                          "long ago": "years ago, when the kids were little, old photos"}},
    "no_people": {"type": "noul", "instructions": "Does the user want photos WITHOUT people in them?"},
    "no_selfies": {"type": "noul", "instructions": "Does the user want to EXCLUDE selfies?"},
}


def jev_key():
    """TYPESAFE_API_KEY from the environment, or from a .env file next to ps.py."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    f = HERE / ".env"
    for line in f.read_text().splitlines() if f.exists() else []:
        if line.strip().startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


@functools.lru_cache(maxsize=256)
def ask_jev(text):
    import urllib.request
    req = urllib.request.Request(JEV_URL, method="POST", headers={"Authorization": f"Bearer {jev_key()}",
                                                                  "Content-Type": "application/json"},
                                 data=json.dumps(dict(model="jev-latest", state=text, questions=JEV_QUESTIONS)).encode())
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.load(r)["answers"]


def parse_query(con, text, today=None):
    """Turn "Sam at the beach last summer, no selfies" into search filters. Names and years are found locally;
    the rest is asked of Jev, which only ever sees the text with tagged names replaced by "someone"."""
    today = today or date.today()
    people = sorted({p for (j,) in con.execute("select persons from photos") for p in json.loads(j)}, key=len, reverse=True)
    firsts = Counter(p.split()[0].lower() for p in people)
    found, masked = [], text
    for p in people:  # full names first, then unambiguous first names
        for name in [p] + ([p.split()[0]] if " " in p and firsts[p.split()[0].lower()] == 1 else []):
            pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
            if pat.search(masked):
                masked = pat.sub("someone", masked); found.append(p); break
    a = ask_jev(masked)
    pick = lambda k: a[k]["choice"] if a[k].get("confidence", 1) >= CHOICE_P else None
    f = dict(person=", ".join(found), kind="", after="", before="", season="", exclude="")
    if pick("kind") in ("photo", "video"):
        f["kind"] = pick("kind")
    if pick("season") in SEASONS:
        f["season"] = pick("season")
    year = re.search(r"\b(19[5-9]\d|20\d\d)\b", text)
    when = "a named year" if year else pick("when")
    y = int(year.group(1)) if year else {"this year": today.year, "last year": today.year - 1}.get(when)
    if y:
        f["after"], f["before"] = f"{y}-01-01", f"{y + 1}-01-01"
        if when == "this year":
            f["before"] = ""
    elif when == "recent":
        f["after"] = (today - timedelta(days=120)).isoformat()
    elif when == "long ago":
        f["before"] = today.replace(year=today.year - 5).isoformat()
    f["exclude"] = ", ".join(x for x, q, p in (("people", "no_people", NO_PEOPLE_P), ("a selfie", "no_selfies", NO_SELFIES_P))
                             if a[q]["noul"] > p)
    return f


def similar(con, uuid, k=24, **f):
    return [r for r in rank(con, vec_of(con, uuid), k + 1, **f) if r["uuid"] != uuid][:k]


def show(results):
    for r in results:
        who = ", ".join(r["persons"])
        print(f"{r['score']:.3f}  {r['date']}  {r['kind']:5}  {r['uuid']}  {r['place'][:40]}  {who}")


def fkw(a):
    return dict(person=a.person, after=a.after, before=a.before, kind=a.kind, place=a.place)


def cmd_search(a): show(search(db(), a.query, a.k, a.exclude, **fkw(a)))
def cmd_similar(a): show(similar(db(), a.uuid, a.k, **fkw(a)))


def cmd_album(a):
    from osxphotos.photosalbum import PhotosAlbum
    res = search(db(), a.query, a.k, **fkw(a))
    order = {r["uuid"]: i for i, r in enumerate(res)}
    photos = sorted(photos_db().photos(uuid=list(order)), key=lambda p: order[p.uuid])
    PhotosAlbum(a.name).add_list(photos)
    print(f"added {len(photos)} photos to album '{a.name}'")


# ---------------------------------------------------------------- fun

def galaxy(con):
    """2-D map of the library (UMAP over the vectors) with named regions. Cached; redone once the index grows 10%."""
    uuids, M, _ = vectors(con)
    f = DATA / "galaxy.json"
    if f.exists():
        g = json.loads(f.read_text())
        if len(g["uuids"]) >= 0.9 * len(uuids):
            return g
    import umap
    from sklearn.cluster import KMeans
    # a high min_dist spreads near-duplicates out, so zooming in shows photos rather than empty space and clumps
    xy = umap.UMAP(n_neighbors=15, min_dist=0.6, spread=1.5, metric="cosine").fit_transform(M)
    lo, hi = np.percentile(xy, 2, 0), np.percentile(xy, 98, 0)  # strays get pinned to the edge
    xy = np.clip((xy - lo) / (hi - lo), 0, 1)
    k = max(2, min(48, len(uuids) // 150))
    cl = KMeans(k, n_init=4, random_state=0).fit_predict(M)
    rows = {r[0]: r[1:] for r in con.execute("select uuid, substr(date,1,4), labels from photos")}
    docs = [set(json.loads(rows[u][1] or "[]")) for u in uuids]
    df = Counter(l for d in docs for l in d)
    regions = []
    for c in range(k):
        idx = np.where(cl == c)[0]
        tf = Counter(l for i in idx for l in docs[i])
        # Apple's labels that are common in this cluster but rare elsewhere
        top = sorted((l for l in tf if tf[l] >= 0.25 * len(idx)),
                     key=lambda l: -tf[l] / len(idx) * np.log(len(docs) / df[l]))[:2]
        cx, cy = np.median(xy[idx], 0)
        regions.append(dict(name=" · ".join(top), x=round(float(cx), 4), y=round(float(cy), 4), n=len(idx)))
    g = dict(uuids=uuids, x=np.round(xy[:, 0], 4).tolist(), y=np.round(xy[:, 1], 4).tolist(),
             year=[int(rows[u][0]) for u in uuids], regions=regions)
    f.write_text(json.dumps(g))
    return g


def timeline(con, query, per=1):
    """The best match for `query` in each year."""
    uuids, M, _ = vectors(con)
    s = M @ embed_query(query)
    years = dict(con.execute("select uuid, substr(date,1,4) from photos"))
    best = {}
    for i in np.argsort(-s):
        y = years.get(uuids[i])
        if y and len(best.setdefault(y, [])) < per:
            best[y].append(i)
    info = photo_info(con, [uuids[i] for v in best.values() for i in v])
    return [dict(year=int(y), results=[dict(info[uuids[i]], score=float(s[i])) for i in best[y]]) for y in sorted(best)]


INTERESTING = ["people at a party or celebration", "a family on vacation", "a beautiful landscape", "kids playing",
               "a city street while travelling", "friends sharing a meal", "a festival or event", "a group photo",
               "a famous landmark", "animals"]
BORING = ["a screenshot of a phone screen", "a photo of a document, receipt or paper", "a dark blurry photo",
          "a whiteboard or a sign with text", "an object photographed for reference", "a photo of a computer screen"]
_interest = (None, None)

def interest(con):
    """How game-worthy each photo looks: closer to INTERESTING than to BORING."""
    global _interest
    uuids, M, _ = vectors(con)
    if _interest[0] is not M:
        good = np.stack([embed_query(t) for t in INTERESTING]); bad = np.stack([embed_query(t) for t in BORING])
        _interest = (M, (M @ good.T).max(1) - (M @ bad.T).max(1))
    return _interest[1]


def game_round(con, mode="year"):
    """A random, reasonably interesting photo to guess the year or place of."""
    uuids, M, _ = vectors(con)
    score = interest(con)
    where = "kind='photo'" + (" and lat is not null" if mode == "place" else "")
    ok = {r[0] for r in con.execute(f"select uuid from photos where {where}")}
    cand = [i for i in np.argsort(-score)[: max(20, len(uuids) * 2 // 5)] if uuids[i] in ok]
    if not cand:
        raise LookupError("no photos to play with yet")
    u = uuids[random.choice(cand)]
    years = con.execute("select min(substr(date,1,4)), max(substr(date,1,4)) from photos").fetchone()
    return dict(photo_info(con, [u])[u], first=int(years[0]), last=int(years[1]))


def photo_math(con, base, plus="", minus="", w=1.0, k=24):
    """base (a photo uuid, or text) + w * (plus - minus), e.g. this photo + "snow" - "summer"."""
    try:
        v, skip = vec_of(con, base), base
    except LookupError:
        v, skip = embed_query(base), None
    d = (embed_query(plus) if plus else 0) - (embed_query(minus) if minus else 0)
    q = v + w * d
    return [r for r in rank(con, (q / np.linalg.norm(q)).astype(np.float32), k + 1) if r["uuid"] != skip][:k]


def photo_jpeg(con, uuid):
    row = con.execute("select src from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(uuid)
    buf = io.BytesIO()
    open_image(row[0]).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def contact_sheet(con, uuids, cols=6, cell=200):
    """One JPEG of numbered thumbnails (1..n in the order given), for Claude to look at many photos at once."""
    from PIL import Image, ImageDraw, ImageFont
    cols = min(cols, len(uuids)) or 1
    sheet = Image.new("RGB", (cols * cell, -(-len(uuids) // cols) * cell), "white")
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default(size=26)
    for n, u in enumerate(uuids):
        im = Image.open(THUMBS / f"{u}.jpg")
        im.thumbnail((cell - 4, cell - 4))
        x, y = n % cols * cell, n // cols * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        draw.rectangle((x + 2, y + 2, x + 40, y + 34), fill="black")
        draw.text((x + 8, y + 4), str(n + 1), fill="white", font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()


# ---------------------------------------------------------------- year in review

REVIEWS = DATA / "reviews"
MONTHS = "January February March April May June July August September October November December".split()


def year_highlights(con, year, n=40):
    """A varied set of the year's best photos, in date order: candidates for a year in review.

    Greedy pick of the most interesting photo (family photos count a little extra), skipping near-duplicates of
    anything already picked and spreading picks across events (runs of photos with no day-long gap)."""
    uuids, M, pos = vectors(con)
    rows = [r for r in con.execute("select uuid, date, persons from photos where kind='photo' and date >= ? and date < ? "
                                   "order by date", (f"{year}-01-01", f"{year + 1}-01-01")) if r[0] in pos]
    if not rows:
        return []
    times = [datetime.fromisoformat(r[1]) for r in rows]
    event = np.cumsum([0] + [(b - a).total_seconds() > 86400 for a, b in zip(times, times[1:])])
    V = M[[pos[r[0]] for r in rows]]
    base = interest(con)[[pos[r[0]] for r in rows]] + 0.02 * np.array([min(len(json.loads(r[2])), 3) for r in rows])
    picked, per_event, closest = [], np.zeros(event[-1] + 1), np.full(len(rows), -1.0)
    for _ in range(min(n, len(rows))):
        val = base - 0.3 * np.clip(closest, 0, None) - 0.04 * per_event[event]
        val[closest > 0.9] = -np.inf  # near-duplicates of a pick (and the picks themselves)
        i = int(np.argmax(val))
        if val[i] == -np.inf:
            break
        picked.append(i); per_event[event[i]] += 1
        closest = np.maximum(closest, V @ V[i])
    info = photo_info(con, [rows[i][0] for i in picked])
    return [dict(info[rows[i][0]], event=int(event[i])) for i in sorted(picked)]


def short_place(place):
    return (place or "").split(",")[0]


def auto_review(con, year, n=30):
    """A year in review without Claude: highlights grouped by month, captioned with who's in them."""
    chapters = []
    for h in year_highlights(con, year, n):
        m = MONTHS[int(h["date"][5:7]) - 1]
        if not chapters or chapters[-1]["month"] != m:
            chapters.append(dict(month=m, photos=[]))
        # the place and date are shown under every photo already, so the caption is just who's in it
        chapters[-1]["photos"].append(dict(uuid=h["uuid"], caption=" & ".join(p.split()[0] for p in h["persons"][:3])))
    for c in chapters:
        c["title"] = c.pop("month")
    return dict(year=year, title=str(year), intro=f"{sum(len(c['photos']) for c in chapters)} moments from {year}",
                made_by="auto", chapters=chapters)


def save_review(review):
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{review['year']}.json").write_text(json.dumps(review, indent=1, ensure_ascii=False))


def load_review(con, year, make=False):
    f = REVIEWS / f"{year}.json"
    if f.exists():
        return json.loads(f.read_text())
    if not make:
        raise LookupError(f"no review for {year}")
    r = auto_review(con, year)
    save_review(r)
    return r


def render_review(con, review, embed=False):
    """The slideshow page for a review. embed=True inlines every photo, making one file you can send to family."""
    import base64
    info = photo_info(con, [p["uuid"] for c in review["chapters"] for p in c["photos"]])
    def src(u):
        return "data:image/jpeg;base64," + base64.b64encode(photo_jpeg(con, u)).decode() if embed else f"/photo/{u}.jpg"
    data = dict(review, chapters=[dict(title=c["title"], text=c.get("text", ""),
                                       photos=[dict(src=src(p["uuid"]), caption=p.get("caption", ""),
                                                    date=info[p["uuid"]]["date"], place=short_place(info[p["uuid"]]["place"]))
                                               for p in c["photos"] if p["uuid"] in info])
                                  for c in review["chapters"]])
    page = (HERE / "review.html").read_text()
    return page.replace("/*REVIEW*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def cmd_review(a):
    con = db()
    if a.auto:
        save_review(auto_review(con, a.year))
    r = load_review(con, a.year, make=True)
    print(f"{r['title']}: {sum(len(c['photos']) for c in r['chapters'])} photos in {len(r['chapters'])} chapters "
          f"(made by {r['made_by']})")
    if a.export:
        Path(a.export).write_text(render_review(con, r, embed=True))
        print(f"wrote {a.export} ({Path(a.export).stat().st_size / 1e6:.1f} MB): one file, opens in any browser")


# ---------------------------------------------------------------- web UI

def cmd_serve(a):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    con = db()
    model()  # warm up before first request

    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]

    def api_search(q):
        f = dict(person=split(q.get("person")), after=q.get("after"), before=q.get("before"), kind=q.get("kind"),
                 months=SEASONS.get(q.get("season")))
        k = int(q.get("k", 48))
        return similar(con, q["like"], k, **f) if "like" in q else search(con, q.get("q", ""), k, split(q.get("exclude")), **f)

    def api_parse(q):  # the smart search box: {"enabled": False} when there's no Jev key
        if not jev_key():
            return dict(enabled=False)
        if not q.get("q"):
            return dict(enabled=True)
        try:
            return dict(enabled=True, filters=parse_query(con, q["q"]))
        except Exception as ex:  # offline, bad key, rate limit: search still works without it
            return dict(enabled=True, error=f"{ex.__class__.__name__}: {ex}")

    def api_open(q):  # reveal in Photos via AppleScript
        import subprocess
        uuid = "".join(c for c in q["uuid"] if c.isalnum() or c in "-/")
        subprocess.run(["osascript", "-e", f'tell application "Photos" to spotlight media item id "{uuid}"'])
        return {}

    def api_info(q):
        info = photo_info(con, [q["uuid"]])
        if not info:
            raise LookupError(q["uuid"])
        return info[q["uuid"]]

    def api_reviews(q):
        made = {int(f.stem): json.loads(f.read_text()) for f in REVIEWS.glob("*.json")} if REVIEWS.exists() else {}
        years = con.execute("select cast(substr(date,1,4) as integer) y, count(*) from photos group by y order by y desc").fetchall()
        return [dict(year=y, photos=n, title=made[y]["title"] if y in made else None,
                     made_by=made[y]["made_by"] if y in made else None) for y, n in years]

    api = {"/api/reviews": api_reviews, "/api/search": api_search, "/api/open": api_open, "/api/info": api_info, "/api/parse": api_parse,
           "/api/galaxy": lambda q: galaxy(con),
           "/api/timeline": lambda q: timeline(con, q.get("q", ""), int(q.get("per", 1))),
           "/api/game": lambda q: game_round(con, q.get("mode", "year")),
           "/api/math": lambda q: photo_math(con, q["base"], q.get("plus", ""), q.get("minus", ""),
                                             float(q.get("w", 1)), int(q.get("k", 24)))}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x): pass

        def send(self, body, ctype, code=200):
            self.send_response(code); self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items() if v[0]}
            if u.path == "/":
                return self.send((HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")  # re-read: edits show on reload
            name = Path(u.path).name
            try:
                if u.path.startswith("/thumb/"):
                    f = THUMBS / name
                    return self.send(f.read_bytes(), "image/jpeg") if f.exists() else self.send(b"", "text/plain", 404)
                if u.path.startswith("/photo/"):
                    return self.send(photo_jpeg(con, name.removesuffix(".jpg")), "image/jpeg")
                if u.path.startswith("/review/") and name.isdigit():
                    page = render_review(con, load_review(con, int(name), make=True), embed="download" in q).encode()
                    if "download" in q:  # one self-contained file to send to family
                        self.send_response(200); self.send_header("content-type", "text/html; charset=utf-8")
                        self.send_header("content-disposition", f'attachment; filename="year-in-review-{name}.html"')
                        self.send_header("content-length", str(len(page))); self.end_headers()
                        return self.wfile.write(page)
                    return self.send(page, "text/html; charset=utf-8")
                if u.path in api:
                    t = time.time(); res = api[u.path](q)
                    total = con.execute("select count(*) from photos").fetchone()[0]
                    return self.send(json.dumps(dict(results=res, ms=int((time.time()-t)*1000), total=total)).encode(),
                                     "application/json")
            except LookupError as ex:
                return self.send(json.dumps(dict(error=str(ex))).encode(), "application/json", 404)
            self.send(b"not found", "text/plain", 404)

    print(f"http://localhost:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("-k", type=int, default=24)
        p.add_argument("--person"); p.add_argument("--after"); p.add_argument("--before"); p.add_argument("--place")
        p.add_argument("--kind", choices=["photo", "video"])

    p = sub.add_parser("index"); p.add_argument("--limit", type=int); p.add_argument("--library")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--vision-tokens", type=int, default=VISION_TOKENS,
                   help="per-image token budget; keep it the same for the whole index"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--exclude", help='e.g. "a selfie"')
    filters(p); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("similar"); p.add_argument("uuid"); filters(p); p.set_defaults(fn=cmd_similar)
    p = sub.add_parser("album"); p.add_argument("name"); p.add_argument("query"); filters(p); p.set_defaults(fn=cmd_album)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("review", help="year in review: build (if needed) and optionally export as one HTML file")
    p.add_argument("year", type=int); p.add_argument("--auto", action="store_true", help="rebuild the automatic version")
    p.add_argument("--export", metavar="FILE.html"); p.set_defaults(fn=cmd_review)
    a = ap.parse_args()
    if getattr(a, "vision_tokens", None):
        globals()["VISION_TOKENS"] = a.vision_tokens
    try:
        a.fn(a)
    except LookupError as ex:
        sys.exit(str(ex))


if __name__ == "__main__":
    main()
