"""Why did this photo match? Where in it, which words, and what the model sees there.

Where: the model cuts a photo into a grid of squares (about 19 x 14) and its vector is the mean of theirs, so each
square's own score against the search is its exact share of the photo's score. A few squares score high against any
search (a patch of sky, a pillar), so a square counts by how much closer it is to the search than to everyday
descriptions (BASE), the same fix as for loud videos. Tested by covering the hottest quarter of 17 photos: their scores
fell by 0.032 on average, against 0.002 for a random quarter and 0.027 for the slow way, covering squares one at a
time (16 s a photo, against 0.5 s). Searches for a whole scene (a backyard, a pool) don't sit in any one part, and
FOCUS says when.

Which words: each word is left out of the search in turn, and the photo's score with and without it compared. A word
that lowers the score is one the photo doesn't fit: "balloon" against a red sun in wildfire smoke.

What it sees: the words of Photos' own labels (used at least SEEN times, but not the COMMON most used, which fit
every photo), closest to the photo first. On 1,500 photos, at least one of the top five was among Photos' labels for
71% of them; the five most used labels, 5%.
"""
import json
from collections import Counter

import numpy as np

from . import embed
from .config import LARGE
from .images import open_image
from .store import vectors

BASE = ["a photo", "a picture of something", "people", "a room", "outdoors", "an object", "a scene", "a background"]
IMAGE_TOKEN = 258880
STOP = {"a", "an", "the", "of", "on", "in", "with", "and", "at", "to", "by", "for", "from", "is", "are", "some", "my", "our"}
SEEN, COMMON = 3, 40
MISFIT = -0.005  # a word whose leaving out raises the score by more than this doesn't fit the photo; less is noise
FOCUS = 0.77  # below this, the match is the whole scene: 0.64-0.74 for a trampoline or a pool, 0.80-0.92 for a dog or a balloon


def tokens(im):
    """(T, W, H): the photo's square vectors in rows, top left first, on a W x H grid."""
    import torch
    m = embed.model(); tr = m[0]
    f = tr.tokenize([im])
    ids, pos = f["input_ids"][0].numpy(), f["image_position_ids"][0].numpy()
    W, H = int(pos[:, 0].max() + 1) // 3, int(pos[:, 1].max() + 1) // 3
    f = {k: (v.to(m.device) if hasattr(v, "to") else v) for k, v in f.items()}
    with embed._model_lock, torch.no_grad():
        T = tr(f)["token_embeddings"][0].float().cpu().numpy()
    T = T[ids == IMAGE_TOKEN]
    if len(T) != W * H:
        raise ValueError(f"{len(T)} squares on a {W} x {H} grid")
    return T, W, H


def heat(T, q, W, H):
    """Each square's score against q, less its score against everyday descriptions: H rows of W."""
    B = np.stack([embed.embed_query(t) for t in BASE])
    return (T @ q - (T @ B.T).mean(1)).reshape(H, W)


def focus(h):
    """How much of the lit part sits in the hottest quarter of squares: 1 if all of it."""
    lit = np.clip(h.ravel(), 0, None)
    return float(np.sort(lit)[::-1][:len(lit) // 4].sum() / lit.sum()) if lit.sum() > 0 else 0.0


def words(v, query):
    """[(word, change)]: how much the photo's score falls when the word is left out (below 0: it doesn't fit)."""
    ws = query.split()
    s = float(v @ embed.embed_query(query))
    out = []
    for i, w in enumerate(ws):
        if w.lower().strip(",.") in STOP or len(ws) == 1:
            continue
        out.append((w, s - float(v @ embed.embed_query(" ".join(ws[:i] + ws[i + 1:])))))
    return out


def vocab(con):
    """(words, their vectors): Photos' labels, embedded once and kept in the index."""
    c = Counter(w for (l,) in con.execute("select labels from photos where kind='photo'") for w in json.loads(l))
    common = {w for w, _ in c.most_common(COMMON)}
    ws = sorted(w for w, n in c.items() if n >= SEEN and w not in common)
    have = {w: np.frombuffer(b, np.float32) for w, b in con.execute("select word, vec from words")}
    if new := [w for w in ws if w not in have]:
        for w in new:
            have[w] = embed.embed_query(w.lower())
        con.executemany("insert or replace into words values(?,?)", [(w, have[w].tobytes()) for w in new]); con.commit()
    return ws, (np.stack([have[w] for w in ws]) if ws else np.zeros((0, len(next(iter(have.values()), [])))))


def sees(con, v, n=8):
    ws, V = vocab(con)
    return [ws[i] for i in np.argsort(-(V @ v))[:n]] if ws else []


def source(con, uuid):
    row = con.execute("select src, kind from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(uuid)
    if row[1] != "photo":
        raise LookupError("only photos can be explained")
    big = LARGE / f"{uuid}.jpg"
    return open_image(big if big.exists() else row[0])


def explain(con, query, uuid):
    """{score, words, sees, heat (H rows of W, 0 to 1), focus, whole}: why this photo matches the search."""
    if not query.strip():
        raise LookupError("no search to explain")
    im = source(con, uuid)
    _, M, pos = vectors(con)
    q = embed.embed_query(query)
    T, W, H = tokens(im)
    h = heat(T, q, W, H)
    v = M[pos[uuid]] if uuid in pos else None
    f = focus(h)
    return dict(score=float(v @ q) if v is not None else None, focus=f, whole=f < FOCUS,
                heat=(np.clip(h, 0, None) / (h.max() if h.max() > 0 else 1)).round(3).tolist(),
                words=[dict(word=w, change=round(c, 4), misfit=c < MISFIT) for w, c in (words(v, query) if v is not None else [])],
                sees=sees(con, v) if v is not None else [])


def overlay(im, h):
    """The photo with what matched lit and the rest dimmed."""
    from PIL import Image
    a = np.clip(np.asarray(h, np.float32), 0, 1) ** 1.5
    mask = Image.fromarray((a * 255).astype(np.uint8)).resize(im.size, Image.BICUBIC)
    dark = Image.blend(im, Image.new("RGB", im.size, (0, 0, 0)), 0.7)
    return Image.composite(im, dark, mask)


def cmd_why(a):
    from .store import db
    con = db()
    uuid = a.uuid
    if len(uuid) < 36:  # a prefix, as `search` prints it in full but people copy less
        rows = con.execute("select uuid from photos where uuid like ?", (uuid + "%",)).fetchall()
        if len(rows) != 1:
            raise LookupError(f"{len(rows)} photos start with {uuid}")
        uuid = rows[0][0]
    r = explain(con, a.query, uuid)
    print(f"score {r['score']:.3f}" if r["score"] is not None else "not in the index yet")
    for w in r["words"]:
        print(f"  {w['word']:16} {w['change']:+.3f}{'   (the photo does not fit this word)' if w['misfit'] else ''}")
    print("sees: " + ", ".join(r["sees"]))
    print(f"focus {r['focus']:.2f}: " + ("the whole scene matches, not one part" if r["whole"] else "lit where it matches"))
    out = a.out or f"why-{uuid[:8]}.jpg"
    overlay(source(con, uuid), r["heat"]).save(out, quality=88)
    print(f"wrote {out}")
