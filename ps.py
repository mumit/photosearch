"""photosearch — semantic search over an Apple Photos library with EmbeddingGemma 2.

  ps.py index  [--limit N] [--library PATH]   embed photos (incremental; safe to re-run)
  ps.py search "kids on a slide" [-k 24] [--person NAME] [--after 2020-01-01] [--before ...]
  ps.py similar UUID [-k 24]                  photos that look like this one
  ps.py serve  [--port 8765]                  local web UI: search, galaxy, time machine, games, photo math
  ps.py album "Name" "query" [-k 50]          put the results into a Photos album
  ps.py today  [--day 08-14]                  photos from this day in earlier years
  ps.py trips                                 trips, found from where photos were taken
  ps.py review 2025|trip-2024-05-02 [--export F.html]   a year or a trip as a slideshow

Nothing is downloaded from iCloud: with "Optimize Mac Storage" on we embed the
local preview Photos keeps (the model only sees ~280 visual tokens anyway).
"""
import argparse, calendar, functools, io, json, math, os, random, re, sqlite3, sys, threading, time, unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DB = DATA / "index.sqlite"
THUMBS = DATA / "thumbs"
MODEL = "google/embeddinggemma-2"
DIM = 768
THUMB_PX = 512     # grid tiles and cards are ~250 px wide, so this is sharp on a Retina screen
LARGE = DATA / "large"  # full-size copies fetched from iCloud, for photos whose local preview is tiny
DISPLAY_PX = 2560  # the most a full-screen view needs
SHARP_PX = 1600    # local previews smaller than this get fetched from iCloud when shown big
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
    if "geo" not in cols:
        con.execute("alter table photos add column geo text")
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


# Timestamps shared by 50+ photos aren't real dates: scans, or a camera whose clock was reset (here 1,042 photos
# say 2002-01-01 00:00). Year-based features (time machine, games, year in review) leave these out.
DATED = "date not in (select date from photos group by date having count(*) >= 50)"


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


def open_image(path, px=1024):
    """The image, upright, in RGB, at most px on its long side (1024 is plenty for the model)."""
    from PIL import Image, ImageOps
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((px, px))
    return im


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
    lib = {p.uuid: p for p in pdb.photos(intrash=False)}
    if lib:  # never prune against an empty read
        gone = done - lib.keys()
        for u in gone:
            con.execute("delete from photos where uuid=?", (u,))
            (THUMBS / f"{u}.jpg").unlink(missing_ok=True)
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
    rows = con.execute(f"select uuid, date, kind, place, persons, lat, lon, not ({DATED}) from photos where uuid in "
                       f"({','.join('?' * len(uuids))})", list(uuids))
    return {r[0]: dict(uuid=r[0], date=r[1][:10], kind=r[2], place=r[3], persons=json.loads(r[4]), lat=r[5], lon=r[6],
                       **({"undated": True} if r[7] else {})) for r in rows}


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
    rows = {r[0]: r[1:] for r in con.execute(f"select uuid, iif({DATED}, substr(date,1,4), 0), labels from photos")}
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
    years = dict(con.execute(f"select uuid, substr(date,1,4) from photos where {DATED}"))
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
          "a whiteboard or a sign with text", "an object photographed for reference", "a photo of a computer screen",
          "a photo of an ID card, passport or credit card"]
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
    where = "kind='photo'" + (" and lat is not null" if mode == "place" else f" and {DATED}")
    ok = {r[0] for r in con.execute(f"select uuid from photos where {where}")}
    cand = [i for i in np.argsort(-score)[: max(20, len(uuids) * 2 // 5)] if uuids[i] in ok]
    if not cand:
        raise LookupError("no photos to play with yet")
    u = uuids[random.choice(cand)]
    years = con.execute(f"select min(substr(date,1,4)), max(substr(date,1,4)) from photos where {DATED}").fetchone()
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


def photo_jpeg(con, uuid, px=DISPLAY_PX, quality=85):
    """The photo as a JPEG at most px on its long side: from its full-size copy if one was fetched, else from the
    best local preview (which, for photos kept only in iCloud, can be as small as 256 px)."""
    row = con.execute("select src from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(uuid)
    big = LARGE / f"{uuid}.jpg"
    if big.exists() and px >= DISPLAY_PX:
        return big.read_bytes()
    buf = io.BytesIO()
    open_image(big if big.exists() else row[0], px).save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------- full-size copies from iCloud

_fetch_lock, _pdb = threading.Lock(), None


def needs_fetch(con, uuid):
    """True if a photo would look soft shown big: no full-size copy yet, and its local preview is under SHARP_PX."""
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()
    if (LARGE / f"{uuid}.jpg").exists():
        return False
    row = con.execute("select src, kind from photos where uuid=?", (uuid,)).fetchone()
    if not row or row[1] != "photo":
        return False
    try:
        return max(Image.open(row[0]).size) < SHARP_PX
    except Exception:
        return True


def fetch_large(con, uuids, log=None):
    """Download full-size versions of photos that need them (see needs_fetch) from iCloud, through Photos with
    PhotoKit (~1 s each), into data/large/ at DISPLAY_PX, and rebuild their thumbnails from them. One fetch at a
    time across threads. Returns how many were fetched. Nothing in the Photos library changes."""
    global _pdb
    import tempfile
    from osxphotos import ExportOptions, PhotoExporter
    n = 0
    for u in dict.fromkeys(uuids):
        with _fetch_lock:
            if not needs_fetch(con, u):
                continue
            if _pdb is None or _pdb.get_photo(u) is None:  # opened once; again if the photo is newer than that
                _pdb = photos_db()
            p = _pdb.get_photo(u)
            if not p:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    r = PhotoExporter(p).export(tmp, options=ExportOptions(download_missing=True, use_photokit=True,
                                                                           edited=p.hasadjustments, timeout=120))
                    files = [f for f in r.exported if Path(f).suffix.lower() not in (".mov", ".mp4", ".aae")]
                    if not files:
                        raise RuntimeError(r.error or "nothing exported")
                    im = open_image(files[0], DISPLAY_PX)
                except Exception as ex:  # offline, or iCloud says no: keep showing the preview
                    if log:
                        log(f"  couldn't fetch {u}: {ex.__class__.__name__}: {ex}")
                    continue
            LARGE.mkdir(parents=True, exist_ok=True)
            tmp_jpg = LARGE / f"{u}.part"
            im.save(tmp_jpg, "JPEG", quality=88)
            tmp_jpg.rename(LARGE / f"{u}.jpg")  # atomic: a reader never sees half a file
            im.thumbnail((THUMB_PX, THUMB_PX)); im.save(THUMBS / f"{u}.jpg", quality=82)
            n += 1
            if log:
                log(f"  fetched {n}: {u}")
    return n


def fetch_in_subprocess(con, uuids, wait=True):
    """fetch_large in a `ps.py fetch` process. PhotoKit hangs on its second request when its first came from a
    worker thread (seen with the web server's), so fetches run on a process's main thread, which can also be
    killed if iCloud stalls. Returns the uuids still needing a fetch afterwards (all of them if not waiting)."""
    import subprocess
    todo = [u for u in dict.fromkeys(uuids) if needs_fetch(con, u)]
    if not todo:
        return []
    cmd = [sys.executable, str(HERE / "ps.py"), "fetch", *todo]
    if not wait:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return todo
    try:
        subprocess.run(cmd, timeout=30 + 10 * len(todo), capture_output=True)
    except subprocess.TimeoutExpired:
        pass
    return [u for u in todo if needs_fetch(con, u)]


class Fetcher:
    """A background thread working through fetch requests in batches, so pages never wait on iCloud."""
    def __init__(self, con):
        import queue
        self.con, self.q, self.failed = con, queue.Queue(), set()
        threading.Thread(target=self.run, daemon=True).start()

    def add(self, uuids):
        for u in uuids:
            self.q.put(u)

    def run(self):
        import queue
        while True:
            batch = [self.q.get()]
            try:
                while len(batch) < 100:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            try:
                left = fetch_in_subprocess(self.con, batch)
            except Exception as ex:
                print(f"fetch: {ex}", file=sys.stderr); left = batch
            self.failed.update(left)

    def status(self, u):
        return "sharp" if (LARGE / f"{u}.jpg").exists() else "failed" if u in self.failed else \
               "fetching" if needs_fetch(self.con, u) else "sharp"


def story_uuids(review):
    return [p["uuid"] for c in review["chapters"] for p in c["photos"]]


def cmd_fetch(a):
    """Full-size copies from iCloud for photos (uuids) or every photo in stories (2025, trip-2024-05-02)."""
    con = db()
    uuids = [u for x in a.what for u in (story_uuids(load_review(con, x, make=True)) if STORY_ID.fullmatch(x) else [x])]
    need = [u for u in dict.fromkeys(uuids) if needs_fetch(con, u)]
    print(f"{len(uuids)} photos, {len(need)} need a full-size copy")
    print(f"fetched {fetch_large(con, need, log=print)}")


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


# ---------------------------------------------------------------- stories: a year or a trip as a slideshow

REVIEWS = DATA / "reviews"
MONTHS = "January February March April May June July August September October November December".split()
STORY_ID = re.compile(r"\d{4}|trip-\d{4}-\d{2}-\d{2}")  # "2025", or a trip by its first day
AWAY_KM = 75   # the next city over, ~95 km away, is a trip
TRIP_MIN = 20  # photos; fewer is a stopover or a ferry ride


def day_after(d):
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def date_range(start, end):
    """ "August 10–18, 2026" """
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    ma, mb = MONTHS[a.month - 1], MONTHS[b.month - 1]
    if a == b:
        return f"{ma} {a.day}, {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{ma} {a.day}–{b.day}, {a.year}"
    if a.year == b.year:
        return f"{ma} {a.day} – {mb} {b.day}, {a.year}"
    return f"{ma} {a.day}, {a.year} – {mb} {b.day}, {b.year}"


def span_photos(con, start, end, home=None):
    """(uuid, date, persons) of the indexed photos from day start to day end (inclusive), in time order. home: a
    (lat, lon) whose photos to leave out, e.g. a trip's first morning at home; photos without a location stay."""
    _, _, pos = vectors(con)
    return [r[:3] for r in con.execute(f"select uuid, date, persons, lat, lon from photos where kind='photo' and date >= ? "
                                       f"and date < ? and {DATED} order by date", (start, day_after(end)))
            if r[0] in pos and not (home and r[3] is not None and km(home, (r[3], r[4])) <= AWAY_KM)]


# Highlights never include photos that look more boring than interesting (interest below 0: ~10% of the library,
# mostly documents, screenshots and ID cards), even when a day has nothing else: better no photo than a passport.
MIN_INTEREST = 0.0


def highlights(con, start, end, n=40, home=None):
    """A varied set of the best photos taken from day start to day end (inclusive), in date order: candidates for a
    review (home as in span_photos). Greedy pick of the most interesting photo (family photos count a little extra),
    skipping near-duplicates of anything already picked and spreading picks across events (runs of photos with no
    day-long gap)."""
    uuids, M, pos = vectors(con)
    rows = span_photos(con, start, end, home)
    if not rows:
        return []
    times = [datetime.fromisoformat(r[1]) for r in rows]
    event = np.cumsum([0] + [(b - a).total_seconds() > 86400 for a, b in zip(times, times[1:])])
    V = M[[pos[r[0]] for r in rows]]
    score = interest(con)[[pos[r[0]] for r in rows]]
    base = score + 0.02 * np.array([min(len(json.loads(r[2])), 3) for r in rows])
    base[score < MIN_INTEREST] = -np.inf
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


def cover(con, start, end):
    """The most interesting photo between two days, for a story's card."""
    uuids, M, pos = vectors(con)
    rows = [r[0] for r in con.execute(f"select uuid from photos where kind='photo' and date >= ? and date < ? and {DATED}",
                                      (start, day_after(end))) if r[0] in pos]
    score = interest(con)
    return max(rows, key=lambda u: score[pos[u]]) if rows else None


def short_place(place):
    return (place or "").split(",")[0]


def km(a, b):
    """Great-circle distance between two (lat, lon) points."""
    la, lb, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return 6371 * math.acos(min(1.0, math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(dl)))


def trip_name(geos):
    """ "Minneapolis & Saint Paul"; the wider area when no one city dominates ("Lisbon", not its boroughs)."""
    geos = [g for g in geos if g]
    top = lambda k: Counter(g[k] for g in geos if k in g).most_common(2)
    city, half = top("city"), len(geos) / 2
    if city and city[0][1] >= half:
        return " & ".join(c for c, n in city if n >= len(geos) / 5)
    for t in (top("water"), top("area"), top("state"), top("country")):
        if t and t[0][1] >= half:
            return t[0][0]
    return " & ".join(c for c, _ in city) or "Trip"


def homes(rows):
    """Home for each year: the ~10 km cell with the most days photographed within 30 km of it. Counting days, not
    photos, and pooling nearby cells keeps a busy week away from outvoting a home spread across several cells."""
    days = defaultdict(lambda: defaultdict(set))
    for d, la, lo, *_ in rows:
        if la is not None:
            days[d[:4]][round(la, 1), round(lo, 1)].add(d[:10])
    def best(cells):
        return max(cells, key=lambda c: len(set().union(*(v for o, v in cells.items() if km(c, o) <= 30))))
    return {y: best(cells) for y, cells in days.items()}


def trips(con):
    """Runs of days spent mostly AWAY_KM+ from home, newest first. Home is worked out per year, so moving house
    doesn't make the new home a trip. A day without location in the middle stays inside the trip; a day
    photographed at home ends it."""
    rows = con.execute(f"select date, lat, lon, geo from photos where {DATED} order by date").fetchall()
    home = homes(rows)
    days = {}
    for d, la, lo, g in rows:
        e = days.setdefault(d[:10], dict(n=0, away=0, home=0, geo=[]))
        e["n"] += 1
        if la is not None and km(home[d[:4]], (la, lo)) > AWAY_KM:
            e["away"] += 1; e["geo"].append(json.loads(g or "{}"))
        elif la is not None:
            e["home"] += 1
    out, cur = [], None
    for d, e in days.items():
        if e["away"] > e["home"]:
            if cur and (date.fromisoformat(d) - date.fromisoformat(cur["end"])).days <= 2:
                cur["end"] = d
            else:
                cur = dict(start=d, end=d, geo=[]); out.append(cur)
            cur["geo"] += e["geo"]
        elif e["home"]:
            cur = None
    for t in out:
        t["photos"] = sum(e["n"] for d, e in days.items() if t["start"] <= d <= t["end"])
        t.update(id=f"trip-{t['start']}", name=trip_name(t.pop("geo")))
    return [t for t in out if t["photos"] >= TRIP_MIN][::-1]


def find_trip(con, rid):
    t = next((t for t in trips(con) if t["id"] == rid), None)
    if not t:
        raise LookupError(f"no trip starting {rid.removeprefix('trip-')} (see `ps.py trips`)")
    return t


def story_span(con, rid):
    """(first day, last day, fields every review of it carries) for a year or a trip. A trip with a saved review
    keeps the days it was made with, even if new photos would now shift where the trip is detected."""
    if not STORY_ID.fullmatch(rid):
        raise LookupError(f"not a story id: {rid!r} (a year like 2025, or a trip like trip-2024-05-02)")
    if rid.isdigit():
        return f"{rid}-01-01", f"{rid}-12-31", dict(id=rid, kind="year", year=int(rid))
    f = REVIEWS / f"{rid}.json"
    t = json.loads(f.read_text()) if f.exists() else find_trip(con, rid)
    return t["start"], t["end"], dict(id=rid, kind="trip", start=t["start"], end=t["end"])


def story_home(con, fields):
    """Home in the year a trip started, so its highlights can skip photos taken there; None for a year."""
    if fields["kind"] != "trip":
        return None
    return homes(con.execute("select date, lat, lon from photos where substr(date,1,4) = ?", (fields["start"][:4],)).fetchall()).get(fields["start"][:4])


def story_highlights(con, rid, n=40):
    start, end, fields = story_span(con, rid)
    return highlights(con, start, end, n, story_home(con, fields))


def auto_review(con, rid, n=30):
    """A review without Claude: highlights grouped by month (a year) or by day (a trip), captioned with who's in them.
    The place and date show under every photo already, so the caption is just the names."""
    start, end, fields = story_span(con, rid)
    trip = fields["kind"] == "trip"
    chapters = []
    for h in story_highlights(con, rid, min(n, max(12, find_trip(con, rid)["photos"] // 10)) if trip else n):
        key = h["date"] if trip else MONTHS[int(h["date"][5:7]) - 1]
        if not chapters or chapters[-1]["key"] != key:
            chapters.append(dict(key=key, photos=[], places=Counter()))
        chapters[-1]["photos"].append(dict(uuid=h["uuid"], caption=" & ".join(p.split()[0] for p in h["persons"][:3])))
        chapters[-1]["places"][short_place(h["place"])] += bool(h["place"])
    for c in chapters:
        key, places = c.pop("key"), c.pop("places")
        if trip:  # "Day 3 · Sintra"
            place = [p for p, k in places.most_common(1) if k]
            key = f"Day {(date.fromisoformat(key) - date.fromisoformat(start)).days + 1}" + "".join(f" · {p}" for p in place)
        c["title"] = key
    n = sum(len(c["photos"]) for c in chapters)
    title = find_trip(con, rid)["name"] if trip else rid
    intro = f"{date_range(start, end)} · {n} moments" if trip else f"{n} moments from {rid}"
    return dict(fields, title=title, intro=intro, made_by="auto", chapters=chapters)


def save_review(review):
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{review['id']}.json").write_text(json.dumps(review, indent=1, ensure_ascii=False))


def load_review(con, rid, make=False):
    f = REVIEWS / f"{rid}.json"
    if f.exists():
        r = json.loads(f.read_text())
        return dict(r, id=rid, kind=r.get("kind", "year"))  # year reviews saved before trips existed
    if not make:
        raise LookupError(f"no review for {rid}")
    r = auto_review(con, rid)
    save_review(r)
    return r


def stories(con):
    """Every trip and year, newest first: its saved review's title and author if it has one, else what was detected."""
    made = {f.stem: json.loads(f.read_text()) for f in REVIEWS.glob("*.json")} if REVIEWS.exists() else {}
    def story(rid, start, end, **x):
        r = made.get(rid, {})
        first = next((p["uuid"] for c in r.get("chapters", []) for p in c["photos"]), None)
        return dict(x, id=rid, start=start, end=end, title=r.get("title", x.get("title")), made_by=r.get("made_by"), edited=r.get("edited"),
                    cover=first or cover(con, start, end))
    found = {t["id"]: t for t in trips(con)}
    for rid, r in made.items():  # a saved trip that new photos have since merged into another, or moved
        if r.get("kind") == "trip" and rid not in found:
            n = con.execute("select count(*) from photos where date >= ? and date < ?", (r["start"], day_after(r["end"])))
            found[rid] = dict(r, photos=n.fetchone()[0], name=r["title"])
    out = [story(t["id"], t["start"], t["end"], kind="trip", title=t["name"], photos=t["photos"])
           for t in sorted(found.values(), key=lambda t: t["start"], reverse=True)]
    years = con.execute(f"select substr(date,1,4) y, count(*) from photos where {DATED} group by y order by y desc")
    return out + [story(y, f"{y}-01-01", f"{y}-12-31", kind="year", title=y, photos=n) for y, n in years.fetchall()]


def story_photos(con, uuids):
    """photo_info plus the full timestamp (photo_info keeps just the day), so the editor can slot photos in by time."""
    if not uuids:
        return {}
    info = photo_info(con, uuids)
    for u, t in con.execute(f"select uuid, date from photos where uuid in ({','.join('?' * len(uuids))})", list(uuids)):
        info[u]["taken"] = t
    return info


def story_for_editor(con, rid):
    r = load_review(con, rid, make=True)
    info = story_photos(con, [p["uuid"] for c in r["chapters"] for p in c["photos"]])
    return dict(r, chapters=[dict(c, photos=[dict(info[p["uuid"]], caption=p.get("caption", ""))
                                             for p in c["photos"] if p["uuid"] in info]) for c in r["chapters"]])


def story_candidates(con, rid, q=None, like=None, k=48):
    """Photos from a story's days to add or swap in: matches for q, look-alikes of like, else its highlights, topped
    up with the rest of its photos in time order when there are few (a short trip has only a handful of highlights)."""
    start, end, fields = story_span(con, rid)
    f = dict(after=start, before=day_after(end), kind="photo")
    if q or like:
        res = search(con, q, k, **f) if q else similar(con, like, k, **f)
    else:
        home = story_home(con, fields)
        res = highlights(con, start, end, k, home)
        have = {r["uuid"] for r in res}
        res += [dict(uuid=r[0]) for r in span_photos(con, start, end, home) if r[0] not in have][:k - len(res)]
    info = story_photos(con, [r["uuid"] for r in res])
    return [info[r["uuid"]] for r in res if r["uuid"] in info]


def edit_review(con, body):
    """Save a story edited in the web page. Its author becomes "you" if it was automatic; Claude's stays Claude's,
    marked edited."""
    rid = str(body.get("id", ""))
    _, _, fields = story_span(con, rid)
    old = load_review(con, rid, make=True)
    text = lambda v, n: str(v or "").strip()[:n]
    chapters = [dict(title=text(c.get("title"), 120) or "Untitled", text=text(c.get("text"), 500),
                     photos=[dict(uuid=text(x.get("uuid"), 64), caption=text(x.get("caption"), 300)) for x in c.get("photos", [])])
                for c in body.get("chapters", [])]
    uuids = [x["uuid"] for c in chapters for x in c["photos"]]
    bad = set(uuids) - photo_info(con, uuids).keys() if uuids else set()
    if bad:
        raise ValueError(f"not in the index: {sorted(bad)}")
    made_by = "you" if old["made_by"] == "auto" else old["made_by"]
    save_review(dict(fields, title=text(body.get("title"), 120) or old["title"], intro=text(body.get("intro"), 300),
                     outro=text(body.get("outro"), 300), made_by=made_by, **({"edited": True} if made_by == "claude" else {}),
                     chapters=chapters))
    return dict(photos=len(uuids), chapters=len(chapters), made_by=made_by)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).strip("-")


def export_name(review):
    if review["kind"] == "year":
        return f"year-in-review-{review['id']}.html"
    return f"{slug(review['title']) or 'trip'}-{review['start'][:4]}.html"


def render_review(con, review, embed=False):
    """The slideshow page for a review. embed=True inlines every photo, making one file you can send to family."""
    import base64
    info = photo_info(con, [p["uuid"] for c in review["chapters"] for p in c["photos"]])
    def src(u):
        # 1600 px: sharp on a laptop or TV, and a 27-photo story is ~13 MB, under email attachment limits
        return "data:image/jpeg;base64," + base64.b64encode(photo_jpeg(con, u, 1600, 80)).decode() if embed else f"/photo/{u}.jpg"
    kicker = date_range(review["start"], review["end"]) if review.get("kind") == "trip" else "Year in review"
    data = dict(review, kicker=kicker,
                chapters=[dict(title=c["title"], text=c.get("text", ""),
                               photos=[dict(src=src(p["uuid"]), caption=p.get("caption", ""),
                                            date=info[p["uuid"]]["date"], place=short_place(info[p["uuid"]]["place"]))
                                       for p in c["photos"] if p["uuid"] in info])
                          for c in review["chapters"]])
    page = (HERE / "review.html").read_text()
    return page.replace("/*REVIEW*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def cmd_trips(a):
    con = db()
    made = {f.stem: json.loads(f.read_text()).get("made_by") for f in REVIEWS.glob("*.json")} if REVIEWS.exists() else {}
    for t in trips(con):
        tag = {"claude": "  ✨ curated", "auto": "  (automatic review)"}.get(made.get(t["id"]), "")
        print(f"{t['id']}  {date_range(t['start'], t['end']):30}  {t['photos']:5} photos  {t['name']}{tag}")


def cmd_review(a):
    con = db()
    if a.auto:
        save_review(auto_review(con, a.story))
    r = load_review(con, a.story, make=True)
    print(f"{r['title']}: {sum(len(c['photos']) for c in r['chapters'])} photos in {len(r['chapters'])} chapters "
          f"(made by {r['made_by']})")
    if a.export:
        if need := [u for u in story_uuids(r) if needs_fetch(con, u)]:
            print(f"fetching full-size copies of {len(need)} photos from iCloud…")
            fetch_large(con, need, log=print)
        Path(a.export).write_text(render_review(con, r, embed=True))
        print(f"wrote {a.export} ({Path(a.export).stat().st_size / 1e6:.1f} MB): one file, opens in any browser")


# ---------------------------------------------------------------- on this day

def on_this_day(con, day=None, per_year=4):
    """The best few photos from this date (MM-DD, default today) in each earlier year, newest first, each with the
    trip it was part of, if any. If no year has photos on the day itself, it's the week around it instead."""
    today = date.today()
    day = day or today.strftime("%m-%d")
    try:
        m, d = map(int, re.fullmatch(r"(\d{2})-(\d{2})", day).groups())
        date(2000, m, d)  # a leap year, so 02-29 is a day
    except (AttributeError, ValueError):
        raise LookupError(f"not a day: {day!r} (MM-DD, e.g. 08-14)")
    years = [int(y) for (y,) in con.execute(f"select distinct substr(date,1,4) from photos where {DATED} order by 1 desc")]
    found = trips(con)
    for window in (0, 3):
        out = []
        for y in years:
            center = date(y, m, min(d, 28) if (m, d) == (2, 29) and not calendar.isleap(y) else d)
            if center >= today:
                continue
            a, b = (center - timedelta(days=window)).isoformat(), (center + timedelta(days=window)).isoformat()
            picks = highlights(con, a, b, per_year)
            if picks:
                t = next((t for t in found if t["start"] <= center.isoformat() <= t["end"]), None)
                out.append(dict(year=y, ago=today.year - y, date=center.isoformat(), photos=picks,
                                trip=t and {k: t[k] for k in ("id", "name", "start", "end")}))
        if out:
            break
    return dict(day=f"{m:02}-{d:02}", window=window, years=out)


def cmd_today(a):
    r = on_this_day(db(), a.day)
    if r["window"]:
        print(f"nothing on {r['day']} itself; the week around it:")
    for y in r["years"]:
        trip = f"  (trip: {y['trip']['name']}, {y['trip']['id']})" if y["trip"] else ""
        ago = "this year" if not y["ago"] else f"{y['ago']} year{'s' * (y['ago'] > 1)} ago"
        print(f"\n{y['year']} · {ago}{trip}")
        show([dict(x, score=0.0) for x in y["photos"]])


# ---------------------------------------------------------------- web UI

def cmd_serve(a):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    con = db()
    model()  # warm up before first request
    fetcher = Fetcher(con)

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

    api = {"/api/today": lambda q: on_this_day(con, q.get("day")), "/api/stories": lambda q: stories(con), "/api/story": lambda q: story_for_editor(con, q.get("id", "")),
           "/api/sharp": lambda q: {u: fetcher.status(u) for u in q.get("uuids", "").split(",") if u},
           "/api/story_photos": lambda q: story_candidates(con, q.get("id", ""), q.get("q"), q.get("like")),
           "/api/search": api_search, "/api/open": api_open, "/api/info": api_info, "/api/parse": api_parse,
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
                if u.path.startswith("/review/") and STORY_ID.fullmatch(name):
                    r = load_review(con, name, make=True)
                    if "download" in q:  # the file goes to family: wait for full-size copies (~1 s per missing one)
                        fetch_in_subprocess(con, story_uuids(r))
                    else:  # the player shows ~5 s per photo, so queued copies arrive ahead of their slides
                        fetcher.add(story_uuids(r))
                    page = render_review(con, r, embed="download" in q).encode()
                    if "download" in q:  # one self-contained file to send to family
                        self.send_response(200); self.send_header("content-type", "text/html; charset=utf-8")
                        self.send_header("content-disposition", f'attachment; filename="{export_name(r)}"')
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

        def do_POST(self):  # the requests that write: saving an edited story, fetching full-size copies
            # Only this page may write. Other sites can't send JSON here without a CORS preflight, which we never
            # answer; checking Host too stops DNS rebinding (a site whose name resolves to 127.0.0.1).
            here = {f"localhost:{a.port}", f"127.0.0.1:{a.port}"}
            origin = self.headers.get("origin")
            if (self.headers.get("host") not in here or (origin and urlparse(origin).netloc not in here)
                    or self.headers.get("content-type", "").split(";")[0].strip() != "application/json"):
                return self.send(b"forbidden", "text/plain", 403)
            path = urlparse(self.path).path
            if path not in ("/api/story", "/api/sharp"):
                return self.send(b"not found", "text/plain", 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
                if path == "/api/sharp":  # fetch full-size copies of these photos from iCloud, in the background
                    uuids = [str(u)[:64] for u in body.get("uuids", [])][:200]
                    fetcher.add(uuids)
                    return self.send(json.dumps(dict(results={u: fetcher.status(u) for u in uuids})).encode(), "application/json")
                res = edit_review(con, body)
                fetcher.add(story_uuids(load_review(con, body["id"])))
            except (ValueError, LookupError, AttributeError, TypeError) as ex:
                return self.send(json.dumps(dict(error=str(ex))).encode(), "application/json", 400)
            self.send(json.dumps(dict(results=res)).encode(), "application/json")

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
    p = sub.add_parser("fetch", help="full-size copies from iCloud for photos whose local preview is small")
    p.add_argument("what", nargs="+", help="story ids (2025, trip-2024-05-02) or photo uuids"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("thumbs", help="rebuild thumbnails at the current size, where the source allows")
    p.set_defaults(fn=cmd_thumbs)
    p = sub.add_parser("today", help="photos from this day in earlier years")
    p.add_argument("--day", help="MM-DD instead of today"); p.set_defaults(fn=cmd_today)
    p = sub.add_parser("trips", help="trips, found from where photos were taken"); p.set_defaults(fn=cmd_trips)
    p = sub.add_parser("review", help="a year or trip as a slideshow: build (if needed), optionally export as one file")
    p.add_argument("story", help="a year (2025) or a trip id from `ps.py trips` (trip-2024-05-02)")
    p.add_argument("--auto", action="store_true", help="rebuild the automatic version")
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
