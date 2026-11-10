"""The index: photos with their vectors and what Photos knows about them, in data/index.sqlite."""
import json, sqlite3, threading
from pathlib import Path

import numpy as np

from .config import DATA, DB, DIM, LIBRARY, THUMBS


def db():
    DATA.mkdir(parents=True, exist_ok=True)
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
    if "flags" not in cols:  # e.g. ["screenshot"]; null until the next `photosearch index`
        con.execute("alter table photos add column flags text")
    if "faces" not in cols:  # {name: [x, y, size]}: where each named person's face is (index.faces); null until `index` runs
        con.execute("alter table photos add column faces text")
    if "quick" not in cols:  # 1 while a photo still has its quick first vector (`index --quick`), until `index` redoes it
        con.execute("alter table photos add column quick integer")
    con.execute("create table if not exists meta(key text primary key, value text)")
    # dates I gave photos whose date in Photos is a placeholder (dates.py), with the date Photos has
    con.execute("""create table if not exists redated(uuid text primary key, date text, photos_date text,
                   precision text, how text, at text)""")
    # each video's sound and its later frames (videos.py)
    con.execute("create table if not exists clips(uuid text, kind text, t real, vec blob, primary key(uuid, kind, t))")
    con.execute("create table if not exists videos_done(uuid text primary key, frames int, sounds int, error text, at text)")
    # old photos I'll shoot again (recreate.py): state todo or done, match the new shot, no the shots that weren't it
    con.execute("""create table if not exists recreate(uuid text primary key, person text, picked text, state text,
                   match text, no text)""")
    # Photos' labels as the model reads them, for "what it sees" (why.py)
    con.execute("create table if not exists words(word text primary key, vec blob)")
    # family picks (picks.py): who loved which photo, and when
    con.execute("create table if not exists picks(uuid text, who text, at text, primary key(uuid, who))")
    # the portrait I chose for someone (people.py), instead of the one picked for them
    con.execute("create table if not exists portrait(name text primary key, uuid text, at text)")
    # the words in each photo, as Vision reads them (text.py); '' when it found none
    con.execute("create table if not exists texts(uuid text primary key, text text, at text)")
    # photos in the library that `index` couldn't read (no preview on this Mac, or an unreadable file); tried each run
    con.execute("create table if not exists skipped(uuid text primary key, reason text, at text)")
    return con


def coverage(con):
    """How much of the library search can find so far, and what each gap needs: what an agent or `photosearch status`
    can tell the user. Only the gaps are listed under "gaps", each with the command that fills it."""
    one = lambda sql: con.execute(sql).fetchone()[0]
    photos, videos = (one(f"select count(*) from photos where kind='{k}'") for k in ("photo", "video"))
    gaps, lib = [], library_uuids()
    if lib is not None:  # what's in Photos that `index` hasn't seen yet, and what's left of photos deleted there
        have, tried = ({u for (u,) in con.execute(f"select uuid from {t}")} for t in ("photos", "skipped"))
        if n := len(lib - have - tried):
            gaps.append(dict(gap="new in Photos since the last index", n=n, fix="`photosearch index`"))
        if n := len(have - lib):
            gaps.append(dict(gap="deleted from Photos, still found by search", n=n, fix="`photosearch index` removes them"))
    if n := one("select count(*) from skipped"):
        why = dict(con.execute("select reason, count(*) from skipped group by reason order by 2 desc").fetchall())
        gaps.append(dict(gap="not indexed", n=n, why=why, fix="`photosearch index` tries them again; one only in "
                         "iCloud needs Photos to download it (turn off Optimize Mac Storage, or open the photo in Photos)"))
    if n := one("select count(*) from photos where quick"):
        gaps.append(dict(gap="quick first vectors, slightly less exact", n=n, fix="`photosearch index` redoes them"))
    read, failed = (one(f"select count(*) from videos_done join photos using(uuid) where error is {x} null") for x in ("", "not"))
    if videos - read:
        gaps.append(dict(gap="videos not searchable by sound or later frames yet", n=videos - read, failed=failed,
                         fix="`photosearch videos --icloud`; ones on the Mac are read by `photosearch index`"))
    if n := one("select count(*) from photos where kind='photo' and uuid not in (select uuid from texts)"):
        gaps.append(dict(gap='words in photos not read yet (searches in "quotes")', n=n, fix="`photosearch text`"))
    if n := one("select count(*) from photos where faces is null"):
        gaps.append(dict(gap="face positions not read (portraits crop around faces)", n=n, fix="`photosearch index`"))
    return dict(photos=photos, videos=videos, gaps=gaps)


# Timestamps shared by 50+ photos aren't real dates: scans, or a camera whose clock was reset (here 1,042 photos
# say 2002-01-01 00:00). Year-based features (time machine, games, year in review) leave these out. Photos I've
# dated (dates.py) have a new date, and their old one stays a placeholder however few photos are left on it.
DATED = ("date not in (select date from photos group by date having count(*) >= 50 "
         "union select photos_date from redated)")


def load_matrix(con, where="", params=()):
    rows = con.execute(f"select uuid, vec from photos {where}", params).fetchall()
    if not rows:
        return [], np.zeros((0, DIM), np.float32)
    return [r[0] for r in rows], np.stack([np.frombuffer(r[1], np.float32) for r in rows])


_vecs = (None, [], np.zeros((0, DIM), np.float32), {})

def vectors(con):
    """All vectors, held in memory and reloaded only when the index changes (e.g. while `index` runs, or redoes quick
    first vectors in place)."""
    global _vecs
    stamp = con.execute("select count(*), max(rowid), count(quick) from photos").fetchone()
    if _vecs[0] != stamp:
        uuids, M = load_matrix(con)
        _vecs = (stamp, uuids, M, {u: i for i, u in enumerate(uuids)})
    return _vecs[1:]


_lib = (None, None)  # (when Photos' database last changed, the uuids in it)


def library_uuids():
    """The uuids of the photos and videos in this index's library (not in the trash), or None if it can't be read
    (no index yet, or no access to Photos). Reading the library takes ~2 s, so it's remembered until Photos'
    database changes."""
    global _lib
    lib = index_library()
    if not lib:
        return None
    try:
        stamp = tuple(f.stat().st_mtime_ns for f in sorted((Path(lib) / "database").glob("Photos.sqlite*"))
                      if not f.name.endswith("-shm"))
        if _lib[0] != stamp:
            _lib = (stamp, {p.uuid for p in photos_db(lib).photos(intrash=False)} or None)  # never empty: a bad read
        return _lib[1]
    except Exception:
        return None


def index_library():
    """The Photos library this index was built from (recorded by `photosearch index`), or None for an older index."""
    row = db().execute("select value from meta where key='library'").fetchone()
    return row[0] if row else None


def photos_db(library=None):
    """The Photos library: the one given, else the one this index was built from, else the system library. So a
    second data folder (PHOTOSEARCH_DATA, e.g. a demo) always reads its own library."""
    import osxphotos
    library = library or index_library()
    if library:
        return osxphotos.PhotosDB(dbfile=library)
    try:
        return osxphotos.PhotosDB()
    except FileNotFoundError:  # newer Photos doesn't record the last library where osxphotos looks
        from osxphotos.utils import get_system_library_path
        return osxphotos.PhotosDB(dbfile=get_system_library_path() or str(LIBRARY))


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
    rows = con.execute(f"select uuid, date, kind, place, persons, lat, lon, not ({DATED}), "
                       f"(select precision from redated r where r.uuid = photos.uuid) from photos where uuid in ({','.join('?' * len(uuids))})", list(uuids))
    return {r[0]: dict(uuid=r[0], date=r[1][:10], kind=r[2], place=r[3], persons=json.loads(r[4]), lat=r[5], lon=r[6],
                       ar=aspect(r[0]), **({"undated": True} if r[7] else {}),
                       **({"approx": r[8]} if r[8] in ("month", "year") else {})) for r in rows}


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
