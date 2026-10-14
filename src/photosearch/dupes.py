"""Tidying up: near-duplicate photos, and which of each group to keep."""
import json
from collections import defaultdict
from datetime import datetime

import numpy as np

from . import photos_app
from .config import DATA, THUMBS
from .store import DATED, aspect, photo_info, vectors
from .search import interest

CLEANUP = DATA / "cleanup.json"   # choices: groups that aren't duplicates, which photo to keep, what went to Photos
MAYBE_DELETE = "Photosearch · maybe delete"
# Calibrated by eye on sample pairs: 0.93-0.95 is the same scene at another moment (a different smile); 0.95-0.97
# similar shots worth choosing between; 0.97+ near-identical bursts; 0.985+ the same picture (also caught across time,
# for copies imported twice).
DUP_LEVELS = {"same": (0.97, 600), "similar": (0.95, 120)}
COPY_SIM = 0.985
# The search model sees every receipt, ID card or game screenshot as nearly the same picture. So:
# - copies far apart in time must also match on a 256-bit difference hash, within 24 bits (measured: real copies
#   3-23, different receipts and IDs 79-149; bursts can't be held to it, people move: 0-134);
# - anything document-like (interest under DOC_LIKE: receipts, IDs; or screen-shaped, narrower than 0.6 or wider
#   than 1.9, like phone screenshots, which can look "interesting" when colourful) only counts when it's practically
#   the same pixels: a mean difference of at most PIXEL_MAX out of 255 at 96x128, and under CHANGED_MAX of the
#   thumbnail's pixels changed by more than 48 (a game screen whose scores changed: 0.2%; real copies: at most 0.04%,
#   though their averages are alike). Missing a duplicate is fine; suggesting a real document for deletion isn't.
HASH_MAX, DOC_LIKE, PIXEL_MAX, CHANGED_MAX = 24, 0.03, 1.0, 0.0005
_dupes, _sharp, _hash, _px = {}, {}, {}, {}

def tiny(u):
    if u not in _px:
        from PIL import Image
        try:
            _px[u] = np.asarray(Image.open(THUMBS / f"{u}.jpg").convert("L").resize((96, 128), Image.LANCZOS), np.float32)
        except Exception:
            _px[u] = np.full((128, 96), -999, np.float32)
    return _px[u]


def same_pixels(a, b):
    if float(np.abs(tiny(a) - tiny(b)).mean()) > PIXEL_MAX:
        return False
    from PIL import Image
    A = Image.open(THUMBS / f"{a}.jpg").convert("L")
    B = Image.open(THUMBS / f"{b}.jpg").convert("L").resize(A.size, Image.LANCZOS)
    return float((np.abs(np.asarray(A, np.float32) - np.asarray(B, np.float32)) > 48).mean()) < CHANGED_MAX

def dhash(u):
    if u not in _hash:
        from PIL import Image
        try:
            a = np.asarray(Image.open(THUMBS / f"{u}.jpg").convert("L").resize((17, 16), Image.LANCZOS), np.int16)
            _hash[u] = (a[:, 1:] > a[:, :-1]).flatten()
        except Exception:
            _hash[u] = np.zeros(256, bool)
    return _hash[u]

def sharpness(uuids):
    """Detail in the thumbnail (variance of its Laplacian, at a common 256 px): the sharper of two near-identical
    shots has more. Cached in data/sharpness.json."""
    f = DATA / "sharpness.json"
    if not _sharp and f.exists():
        _sharp.update(json.loads(f.read_text()))
    todo = [u for u in uuids if u not in _sharp]
    if todo:
        from PIL import Image
        for u in todo:
            try:
                im = Image.open(THUMBS / f"{u}.jpg").convert("L"); im.thumbnail((256, 256))
                g = np.asarray(im, np.float32)
                lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
                _sharp[u] = round(float(lap.var()), 1)
            except Exception:
                _sharp[u] = 0.0
        f.write_text(json.dumps(_sharp))
    return {u: _sharp[u] for u in uuids}


def cleanup_state():
    st = json.loads(CLEANUP.read_text()) if CLEANUP.exists() else {}
    return dict(dict(nope=[], keep={}, sent=[]), **st)


def dupe_groups(con, level="same"):
    """Groups of near-duplicate photos, newest first: runs of shots taken close together that look almost the same,
    plus identical copies wherever they are in time. Each has a pick to keep: the sharpest (then the more
    interesting), unless you chose another."""
    sim, window = DUP_LEVELS[level]
    uuids, M, pos = vectors(con)
    stamp = (len(uuids), level)
    if _dupes.get(level, (None,))[0] != stamp:
        rows = sorted(((u, datetime.fromisoformat(d).timestamp()) for u, d in
                       con.execute(f"select uuid, date from photos where kind='photo' and {DATED}") if u in pos), key=lambda r: r[1])
        ids = [u for u, _ in rows]; ts = np.array([t for _, t in rows]); V = M[[pos[u] for u in ids]]
        parent = list(range(len(ids)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        for k in range(1, 9):  # the next few shots in time
            s = (V[:-k] * V[k:]).sum(1)
            for i in np.where((s >= sim) & (ts[k:] - ts[:-k] <= window))[0]:
                parent[root(i)] = root(i + k)
        for a in range(0, len(ids), 2000):  # the same picture, any time apart
            S = V[a:a + 2000] @ V.T
            for i, j in zip(*np.where(S >= COPY_SIM)):
                if j > i + a:
                    parent[root(i + a)] = root(j)
        comps = defaultdict(list)
        for i in range(len(ids)):
            comps[root(i)].append(i)
        score = interest(con)
        doc = lambda i: score[pos[ids[i]]] < DOC_LIKE or not 0.6 <= aspect(ids[i]) <= 1.9
        def alike(i, seed):  # no chains drifting across a whole afternoon: everyone must resemble the first
            if float(V[i] @ V[seed]) < sim - 0.015:
                return False
            if i == seed:
                return True
            if doc(i) or doc(seed):
                return same_pixels(ids[i], ids[seed])
            if abs(ts[i] - ts[seed]) > window:
                return int((dhash(ids[i]) != dhash(ids[seed])).sum()) <= HASH_MAX
            return True
        groups = []
        for c in comps.values():
            while len(c) > 1:
                seed = c[0]
                g = [i for i in c if alike(i, seed)]
                if len(g) > 1:
                    groups.append(g)
                c = [i for i in c if i not in set(g)] if len(g) > 1 else c[1:]
        out = []
        for g in groups:
            us = [ids[i] for i in g]
            far = ts[g].max() - ts[g].min() > window
            out.append(dict(key="|".join(sorted(us)), uuids=us, kind="copy" if far else "burst", t=float(ts[g].max())))
        out.sort(key=lambda g: -g["t"])
        _dupes[level] = (stamp, out)
    return _dupes[level][1]


def dupe_keeper(con, g, st):
    """(the photo to keep, why): the one you picked, else the sharpest, with interest as a tie-breaker."""
    if st["keep"].get(g["key"]) in g["uuids"]:
        return st["keep"][g["key"]], "your pick"
    score = interest(con); _, _, pos = vectors(con)
    sh = sharpness(g["uuids"]); top = max(sh.values()) or 1
    return max(g["uuids"], key=lambda u: sh[u] / top + 2 * score[pos[u]]), "the sharpest"


def dupes(con, level="same", offset=0, limit=24):
    st = cleanup_state()
    sent = set(st["sent"])
    groups = [g for g in dupe_groups(con, level) if g["key"] not in set(st["nope"])]
    keeper = lambda g: dupe_keeper(con, g, st)
    page = groups[offset:offset + limit]
    info = photo_info(con, [u for g in page for u in g["uuids"]])
    out = []
    for g in page:
        keep, why = keeper(g)
        out.append(dict(key=g["key"], kind=g["kind"], keep=keep, why=why,
                        photos=[dict(info[u], sent=u in sent) for u in g["uuids"] if u in info]))
    return dict(groups=out, total=len(groups), extra=sum(len(g["uuids"]) - 1 for g in groups),
                sent=len(sent), level=level, album=MAYBE_DELETE)


def dupes_choose(con, body):
    st = cleanup_state()
    key = str(body.get("key") or "")
    if body.get("action") == "keep":
        st["keep"][key] = str(body.get("uuid"))[:64]
    elif body.get("action") == "nope":
        st["nope"] = sorted(set(st["nope"]) | {key})
    else:
        raise ValueError("action is keep or nope")
    CLEANUP.write_text(json.dumps(st))
    return {}


def dupes_send(con, level="same"):
    """Every extra (all but each group's keeper) that isn't in the maybe-delete album yet goes there, in Photos."""
    st = cleanup_state(); sent = set(st["sent"])
    nope = set(st["nope"])
    extras = []
    for g in dupe_groups(con, level):
        if g["key"] not in nope:
            keep = dupe_keeper(con, g, st)[0]  # by the same rule the page shows
            extras += [u for u in g["uuids"] if u != keep and u not in sent]
    n = photos_app.add_to_photos_album(MAYBE_DELETE, extras)
    st = cleanup_state(); st["sent"] = sorted(set(st["sent"]) | set(extras)); CLEANUP.write_text(json.dumps(st))
    return dict(added=n, album=MAYBE_DELETE)
