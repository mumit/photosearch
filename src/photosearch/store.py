"""The index: photos with their vectors and what Photos knows about them, in data/index.sqlite."""
import json, sqlite3, threading

import numpy as np

from .config import DATA, DB, DIM, LIBRARY, THUMBS


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


_ar = {}

def aspect(uuid):
    """Width / height of the thumbnail (it keeps the photo's shape), so the page can lay out rows before images load."""
    if uuid not in _ar:
        try:
            from PIL import Image
            w, h = Image.open(THUMBS / f"{uuid}.jpg").size  # reads the header only
            _ar[uuid] = round(w / h, 3)
        except Exception:
            return 1.0
    return _ar[uuid]


def photo_info(con, uuids):
    rows = con.execute(f"select uuid, date, kind, place, persons, lat, lon, not ({DATED}) from photos where uuid in "
                       f"({','.join('?' * len(uuids))})", list(uuids))
    return {r[0]: dict(uuid=r[0], date=r[1][:10], kind=r[2], place=r[3], persons=json.loads(r[4]), lat=r[5], lon=r[6],
                       ar=aspect(r[0]), **({"undated": True} if r[7] else {})) for r in rows}


def vec_of(con, uuid):
    row = con.execute("select vec from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(f"{uuid} not indexed")
    return np.frombuffer(row[0], np.float32)


class ThreadCon:
    """A connection per thread. The server answers requests in parallel, and queries interleaved on one shared
    sqlite connection hand back each other's rows."""
    def __init__(self):
        self.local = threading.local()

    def __getattr__(self, name):
        if not hasattr(self.local, "con"):
            self.local.con = db()
        return getattr(self.local.con, name)
