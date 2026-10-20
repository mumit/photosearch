"""`photosearch index`: read the Photos library and embed what's new."""
import json, sys, time
from pathlib import Path

import numpy as np

from . import embed
from .config import LARGE, MODEL, THUMBS, THUMB_PX
from .dates import apply as apply_dates
from .store import db, photos_db
from .images import open_image
from .text import read_all as read_text
from .videos import embed_videos, forget as forget_video


def check_settings(con):
    """Vectors from different models or vision-token budgets don't mix, so pin them on first index."""
    have = dict(con.execute("select key, value from meta"))
    for k, v in (("model", MODEL), ("vision_tokens", str(embed.VISION_TOKENS))):
        if k in have and have[k] != v:
            sys.exit(f"index was built with {k}={have[k]}, not {v}; use that, or delete data/ and re-index")
        con.execute("insert or ignore into meta values(?,?)", (k, v))
    con.commit()


# `index --quick`: a first index at 70 vision tokens, about 5x faster (27 min for 17,000 photos, not 2 h 20), redone
# at the full 280 by the next plain `index`, newest first. A quick vector scores 0.019 higher against words than the
# full one, so while some photos are quick they'd crowd every search: with a quarter left, half of each search's first
# 24. Moving each quick vector that far back along the direction words share (QUICK_WORDS, the app's own) fixed it on
# 2,000 photos and 25 searches held out: each kind took its share of the first 24, and 18.2-21.8 of them were the same
# as with every photo at 280 (15.6-18.4 without the fix).
QUICK_TOKENS, QUICK_GAP = 70, 0.019
QUICK_WORDS = ["a photo", "people", "a room", "outdoors", "a child posing for the camera"]


def quick_shift():
    from .search import BORING, INTERESTING
    m = np.stack([embed.embed_query(t) for t in INTERESTING + BORING + QUICK_WORDS]).mean(0)
    return (QUICK_GAP * m / (m @ m)).astype(np.float32)


def best_local_image(p):
    """Largest on-disk preview (fast to decode; for videos it's the poster frame), else a local original."""
    ders = [d for d in (p.path_derivatives or []) if Path(d).exists()]
    if ders:
        return ders[0]  # osxphotos returns largest first
    if p.isphoto and p.path and Path(p.path).exists():
        return p.path
    return None


def geo(p):
    """Structured place names, for naming trips. Photos' "city" can be a borough (Santa Maria Maior), its "area" the city."""
    if not p.place:
        return "{}"
    n = p.place.names
    first = lambda *xs: next((x[0] for x in xs if x), None)
    g = dict(city=first(n.city), area=first(n.sub_administrative_area), state=first(n.state_province),
             country=first(n.country), water=first(n.body_of_water, n.ocean, n.inland_water))
    return json.dumps({k: v for k, v in g.items() if v}, ensure_ascii=False)


def meta(p):
    """Everything we keep about a photo except its vector: cheap to recompute, so refreshed on every index run."""
    lat, lon = p.location or (None, None)
    return (p.date.isoformat(), "video" if p.ismovie else "photo", p.title or "",
            (p.place.name if p.place else "") or "",
            json.dumps(list(dict.fromkeys(x for x in p.persons if x != "_UNKNOWN_"))), json.dumps(p.albums),
            json.dumps(p.labels), lat, lon, geo(p), json.dumps([f for f in FLAGS if getattr(p, f, False)]), json.dumps(faces(p)))


FLAGS = ("screenshot", "selfie")  # what Photos knows about how a photo was made
META_COLS = "date, kind, title, place, persons, albums, labels, lat, lon, geo, flags, faces"
def faces(p):
    """{name: [x, y, size]} for the people Photos has found in a photo: the face's centre as fractions of the photo's
    width and height as shown, and its size as a fraction of the photo's longer side. For portraits (people.py)."""
    out = {}
    for f in getattr(p, "face_info", None) or []:
        if f.name and f.name != "_UNKNOWN_" and f.size > 0 and f.size > out.get(f.name, [0, 0, 0])[2]:
            # Photos counts up from the bottom of the photo as shown, whatever its orientation (checked against
            # Apple's face detector on 40 photos of each orientation: within 2% of the face)
            out[f.name] = [round(f.center_x, 4), round(1 - f.center_y, 4), round(f.size, 4)]
    return out
N_META = len(META_COLS.split(","))


def cmd_index(a):
    con = db()
    check_settings(con)
    THUMBS.mkdir(parents=True, exist_ok=True)
    done = {r[0] for r in con.execute("select uuid from photos")}
    print("opening Photos library…", flush=True)
    pdb = photos_db(a.library)
    print(f"library: {pdb.library_path}")
    # one index, one library: indexing another into it would drop every photo the other one doesn't have
    have = con.execute("select value from meta where key='library'").fetchone()
    if have and Path(have[0]).resolve() != Path(pdb.library_path).resolve():
        sys.exit(f"this index is of {have[0]}, not {pdb.library_path}; for another library, use another data folder "
                 "(PHOTOSEARCH_DATA=...)")
    con.execute("insert or ignore into meta values('library', ?)", (str(pdb.library_path),)); con.commit()
    lib = {p.uuid: p for p in pdb.photos(intrash=False)}
    if lib:  # never prune against an empty read
        gone = done - lib.keys()
        for u in gone:
            con.execute("delete from photos where uuid=?", (u,))
            con.execute("delete from texts where uuid=?", (u,))
            (THUMBS / f"{u}.jpg").unlink(missing_ok=True)
            (LARGE / f"{u}.jpg").unlink(missing_ok=True)  # and its full-size copy, if one was fetched
            forget_video(con, u)
        keep = done & lib.keys()
        con.executemany(f"update photos set ({META_COLS}) = ({','.join('?' * N_META)}) where uuid=?",
                        [meta(lib[u]) + (u,) for u in keep])
        con.commit()
        apply_dates(con)  # Photos still has the placeholder dates; keep mine
        print(f"refreshed {len(keep)}, removed {len(gone)} deleted from the library")
        done = keep
    todo = [p for u, p in lib.items() if u not in done]
    todo.sort(key=lambda p: p.date, reverse=True)
    quick = getattr(a, "quick", False)
    if quick and embed.VISION_TOKENS != 280:
        sys.exit("--quick is for an index at the default 280 vision tokens")
    redo = [] if quick or embed.VISION_TOKENS != 280 else \
        sorted((lib[u] for (u,) in con.execute("select uuid from photos where quick") if u in lib), key=lambda p: p.date, reverse=True)
    todo += redo
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(done)} already indexed, {len(todo) - len(redo)} to go" + (f", {len(redo)} quick ones to redo" if redo else "") +
          f" (vision tokens: {QUICK_TOKENS if quick else embed.VISION_TOKENS})")
    m = embed.model()
    if quick:
        embed.set_vision_tokens(m, QUICK_TOKENS); shift = quick_shift()
    t0, n, skipped, batch = time.time(), 0, 0, []

    def flush():
        nonlocal n
        if not batch:
            return
        vecs = m.encode([{"image": im} for _, im, _ in batch], batch_size=len(batch),
                        normalize_embeddings=True).astype(np.float32)
        if quick:
            vecs = vecs - shift
        for (p, im, src), v in zip(batch, vecs):
            th = im.copy(); th.thumbnail((THUMB_PX, THUMB_PX))
            th.save(THUMBS / f"{p.uuid}.jpg", quality=82)
            con.execute(f"insert or replace into photos (uuid, {META_COLS}, src, vec, quick) values ({','.join('?' * (N_META + 4))})",
                        (p.uuid, *meta(p), src, v.tobytes(), 1 if quick else None))
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
    if quick:
        embed.set_vision_tokens(m, embed.VISION_TOKENS)
        print("search works now; a plain `photosearch index` later redoes these at full quality, newest first")
    if not a.limit and not a.no_videos and not quick:  # new videos already on this Mac: their sound and frames (videos.py)
        embed_videos(con, pdb)
    if not a.limit and not quick:  # the words in new photos (text.py), about 20 a second
        read_text(con)


def cmd_thumbs(a):
    """Rebuild thumbnails at THUMB_PX where the photo's source is bigger than its current thumbnail."""
    from PIL import Image
    con, n, t0 = db(), 0, time.time()
    rows = con.execute("select uuid, src from photos").fetchall()
    for i, (u, src) in enumerate(rows):
        th, big = THUMBS / f"{u}.jpg", LARGE / f"{u}.jpg"
        try:
            have = max(Image.open(th).size) if th.exists() else 0
            source = big if big.exists() else src
            if have >= THUMB_PX or (have and max(Image.open(source).size) <= have):
                continue
            im = open_image(source, THUMB_PX); im.save(th, quality=82); n += 1
        except Exception as ex:
            print(f"\n  skip {u}: {ex.__class__.__name__}: {ex}")
        if i % 200 == 0:
            print(f"\r{i}/{len(rows)}  rebuilt {n}", end="", flush=True)
    print(f"\rrebuilt {n} of {len(rows)} thumbnails in {(time.time() - t0) / 60:.1f} min")
