"""While `serve` runs, new photos in Photos are indexed by themselves, so a search finds them without anyone running
`photosearch index`. Not a background service: it stops when `serve` does, and `serve --no-index` turns it off.

It looks a minute after `serve` starts and then every quarter of an hour, comparing the library with the index
(store.library_uuids, read again only when Photos' database changes). New photos are indexed by a `photosearch index
--only-new --no-videos` process at low priority, so searches stay quick and a crash can't take `serve` with it. Quick
vectors and new videos' sound wait for a plain `index`. Only one `index` runs on a data folder at a time."""
import os, subprocess, sys, threading, time

from .config import DATA
from .store import db, library_uuids

FIRST, EVERY = 60, 15 * 60  # seconds: a minute after `serve` starts, then every quarter of an hour
COMMAND = [sys.executable, "-m", "photosearch", "index", "--only-new", "--no-videos"]


def new_photos(con):
    """How many photos and videos are in Photos but not in this index, leaving out ones `index` tried and skipped."""
    lib = library_uuids()
    if not lib:
        return 0
    have = {u for (u,) in con.execute("select uuid from photos union select uuid from skipped")}
    return len(lib - have)


def check(con, log=print):
    """Index whatever is new. Returns how many were new (0: nothing ran)."""
    n = new_photos(con)
    if n:
        log(f"indexing {n:,} new from Photos…")
        with open(DATA / "index.log", "a") as f:
            r = subprocess.run(COMMAND, stdout=f, stderr=subprocess.STDOUT, preexec_fn=lambda: os.nice(10))
        log("indexed: they're in searches now" if r.returncode == 0 else
            f"indexing stopped (exit {r.returncode}), tried again later; see {DATA / 'index.log'}")
    return n


def start(log=print):
    """Look for new photos now and then, for as long as this process runs."""
    def loop():
        con = db()
        time.sleep(FIRST)
        while True:
            try:
                check(con, log)
            except Exception as ex:  # an unreadable library, say: try again next time
                log(f"looking for new photos: {ex.__class__.__name__}: {ex}")
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True, name="new photos").start()
