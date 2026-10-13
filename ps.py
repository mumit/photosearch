"""photosearch — semantic search over an Apple Photos library with EmbeddingGemma 2.

  ps.py index  [--limit N] [--library PATH]   embed photos (incremental; safe to re-run)
  ps.py search "kids on a slide" [-k 24] [--person NAME] [--after 2020-01-01] [--before ...]
  ps.py similar UUID [-k 24]                  photos that look like this one
  ps.py serve  [--port 8765]                  local web UI
  ps.py album "Name" "query" [-k 50]          put the results into a Photos album

Nothing is downloaded from iCloud: with "Optimize Mac Storage" on we embed the
local preview Photos keeps (the model only sees ~280 visual tokens anyway).
"""
import argparse, io, json, sqlite3, sys, time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DB = DATA / "index.sqlite"
THUMBS = DATA / "thumbs"
MODEL = "google/embeddinggemma-2"
DIM = 768
THUMB_PX = 360


# ---------------------------------------------------------------- storage

def db():
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""create table if not exists photos(
        uuid text primary key, date text, kind text, title text, place text,
        persons text, albums text, labels text, src text, vec blob)""")
    return con


def load_matrix(con, where="", params=()):
    rows = con.execute(f"select uuid, vec from photos {where}", params).fetchall()
    if not rows:
        return [], np.zeros((0, DIM), np.float32)
    return [r[0] for r in rows], np.stack([np.frombuffer(r[1], np.float32) for r in rows])


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


def cmd_index(a):
    import osxphotos
    from PIL import Image
    con = db()
    THUMBS.mkdir(parents=True, exist_ok=True)
    done = {r[0] for r in con.execute("select uuid from photos")}
    print("opening Photos library…", flush=True)
    pdb = osxphotos.PhotosDB(dbfile=a.library) if a.library else osxphotos.PhotosDB()
    print(f"library: {pdb.library_path}")
    todo = [p for p in pdb.photos(intrash=False) if p.uuid not in done]
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
            con.execute("insert or replace into photos values(?,?,?,?,?,?,?,?,?,?)", (
                p.uuid, p.date.isoformat(), "video" if p.ismovie else "photo", p.title or "",
                (p.place.name if p.place else "") or "",
                json.dumps([x for x in p.persons if x != "_UNKNOWN_"]), json.dumps(p.albums),
                json.dumps(p.labels), src, v.tobytes()))
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

def filtered(con, person=None, after=None, before=None, kind=None):
    clauses, params = [], []
    if person:
        clauses.append("exists (select 1 from json_each(persons) where lower(value) like ?)"); params.append(f"%{person.lower()}%")
    if after:
        clauses.append("date >= ?"); params.append(after)
    if before:
        clauses.append("date < ?"); params.append(before)
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    return load_matrix(con, ("where " + " and ".join(clauses)) if clauses else "", params)


def rank(con, qvec, k, **filters):
    uuids, M = filtered(con, **filters)
    if not uuids:
        return []
    scores = M @ qvec
    top = np.argsort(-scores)[:k]
    meta = {r[0]: r for r in con.execute(
        f"select uuid, date, kind, place, persons from photos where uuid in ({','.join('?'*len(top))})",
        [uuids[i] for i in top])}
    return [dict(uuid=uuids[i], score=float(scores[i]), date=meta[uuids[i]][1][:10], kind=meta[uuids[i]][2],
                 place=meta[uuids[i]][3], persons=json.loads(meta[uuids[i]][4])) for i in top]


def search(con, query, k=24, **f):
    return rank(con, embed_query(query), k, **f)


def similar(con, uuid, k=24, **f):
    row = con.execute("select vec from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        sys.exit(f"{uuid} not indexed")
    return [r for r in rank(con, np.frombuffer(row[0], np.float32), k + 1, **f) if r["uuid"] != uuid][:k]


def show(results):
    for r in results:
        who = ", ".join(r["persons"])
        print(f"{r['score']:.3f}  {r['date']}  {r['kind']:5}  {r['uuid']}  {r['place'][:40]}  {who}")


def fkw(a):
    return dict(person=a.person, after=a.after, before=a.before, kind=a.kind)


def cmd_search(a): show(search(db(), a.query, a.k, **fkw(a)))
def cmd_similar(a): show(similar(db(), a.uuid, a.k, **fkw(a)))


def cmd_album(a):
    import osxphotos
    from osxphotos.photosalbum import PhotosAlbum
    res = search(db(), a.query, a.k, **fkw(a))
    pdb = osxphotos.PhotosDB()
    photos = pdb.photos(uuid=[r["uuid"] for r in res])
    PhotosAlbum(a.name).add_list(photos)
    print(f"added {len(photos)} photos to album '{a.name}'")


# ---------------------------------------------------------------- web UI

def cmd_serve(a):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    con = sqlite3.connect(DB, check_same_thread=False)
    model()  # warm up before first request
    page = (HERE / "ui.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x): pass

        def send(self, body, ctype, code=200):
            self.send_response(code); self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items() if v[0]}
            if u.path == "/":
                return self.send(page, "text/html; charset=utf-8")
            if u.path.startswith("/thumb/"):
                f = THUMBS / (Path(u.path).name)
                return self.send(f.read_bytes(), "image/jpeg") if f.exists() else self.send(b"", "text/plain", 404)
            if u.path == "/api/search":
                f = dict(person=q.get("person"), after=q.get("after"), before=q.get("before"), kind=q.get("kind"))
                k = int(q.get("k", 48)); t = time.time()
                res = similar(con, q["like"], k, **f) if "like" in q else search(con, q.get("q", ""), k, **f)
                total = con.execute("select count(*) from photos").fetchone()[0]
                return self.send(json.dumps(dict(results=res, ms=int((time.time()-t)*1000), total=total)).encode(),
                                 "application/json")
            if u.path == "/api/open":  # reveal in Photos via AppleScript
                import subprocess
                uuid = q["uuid"].replace('"', "")
                subprocess.run(["osascript", "-e", f'tell application "Photos" to spotlight media item id "{uuid}"'])
                return self.send(b"{}", "application/json")
            self.send(b"not found", "text/plain", 404)

    print(f"http://localhost:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("-k", type=int, default=24)
        p.add_argument("--person"); p.add_argument("--after"); p.add_argument("--before")
        p.add_argument("--kind", choices=["photo", "video"])

    p = sub.add_parser("index"); p.add_argument("--limit", type=int); p.add_argument("--library")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--vision-tokens", type=int, default=VISION_TOKENS,
                   help="per-image token budget; keep it the same for the whole index"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("search"); p.add_argument("query"); filters(p); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("similar"); p.add_argument("uuid"); filters(p); p.set_defaults(fn=cmd_similar)
    p = sub.add_parser("album"); p.add_argument("name"); p.add_argument("query"); filters(p); p.set_defaults(fn=cmd_album)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.set_defaults(fn=cmd_serve)
    a = ap.parse_args()
    if getattr(a, "vision_tokens", None):
        globals()["VISION_TOKENS"] = a.vision_tokens
    a.fn(a)


if __name__ == "__main__":
    main()
