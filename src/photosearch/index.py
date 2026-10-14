"""`photosearch index`: read the Photos library and embed what's new."""
import json, sys, time
from pathlib import Path

import numpy as np

from . import embed
from .config import LARGE, MODEL, THUMBS, THUMB_PX
from .store import db, photos_db
from .images import open_image


def check_settings(con):
    """Vectors from different models or vision-token budgets don't mix, so pin them on first index."""
    have = dict(con.execute("select key, value from meta"))
    for k, v in (("model", MODEL), ("vision_tokens", str(embed.VISION_TOKENS))):
        if k in have and have[k] != v:
            sys.exit(f"index was built with {k}={have[k]}, not {v}; use that, or delete data/ and re-index")
        con.execute("insert or ignore into meta values(?,?)", (k, v))
    con.commit()


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
            json.dumps(p.labels), lat, lon, geo(p))


META_COLS = "date, kind, title, place, persons, albums, labels, lat, lon, geo"
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
            (THUMBS / f"{u}.jpg").unlink(missing_ok=True)
            (LARGE / f"{u}.jpg").unlink(missing_ok=True)  # and its full-size copy, if one was fetched
        keep = done & lib.keys()
        con.executemany(f"update photos set ({META_COLS}) = ({','.join('?' * N_META)}) where uuid=?",
                        [meta(lib[u]) + (u,) for u in keep])
        con.commit()
        print(f"refreshed {len(keep)}, removed {len(gone)} deleted from the library")
        done = keep
    todo = [p for u, p in lib.items() if u not in done]
    todo.sort(key=lambda p: p.date, reverse=True)
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(done)} already indexed, {len(todo)} to go (vision tokens: {embed.VISION_TOKENS})")
    m = embed.model()
    t0, n, skipped, batch = time.time(), 0, 0, []

    def flush():
        nonlocal n
        if not batch:
            return
        vecs = m.encode([{"image": im} for _, im, _ in batch], batch_size=len(batch),
                        normalize_embeddings=True).astype(np.float32)
        for (p, im, src), v in zip(batch, vecs):
            th = im.copy(); th.thumbnail((THUMB_PX, THUMB_PX))
            th.save(THUMBS / f"{p.uuid}.jpg", quality=82)
            con.execute(f"insert or replace into photos (uuid, {META_COLS}, src, vec) values ({','.join('?' * (N_META + 3))})",
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
