"""While `serve` runs, the library is indexed by itself, so a search finds new photos without anyone running
`photosearch index`. Not a background service: it stops when `serve` does, and so does any `index` it started
(index.stop_with), and `serve --no-index` turns it off.

On a fresh install, with nothing indexed, it starts the first index at once, quick (`index --quick`, about 4× faster),
newest first, so searches work on the newest photos within minutes and the page shows how far it has got
(`progress`). Then it looks every quarter of an hour, comparing the library with the index (store.library_uuids,
read again only when Photos' database changes): new photos are indexed by `index --only-new --no-videos`, and once
none are new, the quick ones are redone at full quality by a plain `index --no-videos`. Each runs in a process of its
own at low priority, so searches stay quick and a crash can't take `serve` with it. New videos' sound waits for a
plain `index`. Only one `index` runs on a data folder at a time."""
import os, re, subprocess, sys, threading, time

from .config import DATA
from .store import db, index_library, library_uuids

FIRST, EVERY = 60, 15 * 60  # seconds: a minute after `serve` starts, then every quarter of an hour
INDEX = [sys.executable, "-m", "photosearch", "index"]
COMMAND = INDEX + ["--only-new", "--no-videos"]
FIRST_INDEX = INDEX + ["--quick"]  # quick skips videos and the words in photos; the redo reads the words
REDO = INDEX + ["--no-videos"]
NO_ACCESS = re.compile(r"permission|not permitted|unable to open|authoriz", re.I)
state: dict = dict(job=None, since=None, error=None)  # what's running now, and why the last run stopped, for the page


def new_photos(con):
    """How many photos and videos are in Photos but not in this index, leaving out ones `index` tried and skipped."""
    lib = library_uuids()
    if not lib:
        return 0
    have = {u for (u,) in con.execute("select uuid from photos union select uuid from skipped")}
    return len(lib - have)


def job(con):
    """(what to do, how many, its command), or None: a first index of a fresh install, else the photos new in
    Photos, else the quick first vectors to redo at full quality."""
    if not index_library() and not con.execute("select 1 from photos limit 1").fetchone():
        return "first", None, FIRST_INDEX
    if n := new_photos(con):
        return "new", n, COMMAND
    if n := con.execute("select count(*) from photos where quick").fetchone()[0]:
        return "redo", n, REDO
    return None


def last_line(log, start):
    """The last line `index` wrote to the log from byte start on: why it stopped."""
    with open(log, "rb") as f:
        f.seek(start)
        lines = [x.strip() for x in re.split(r"[\r\n]", f.read().decode(errors="replace")) if x.strip()]
    return lines[-1] if lines else ""


def check(con, log=print):
    """Do whatever needs doing. Returns how many photos were new (0 for a first index or a redo, or nothing to do)."""
    todo = job(con)
    if not todo:
        return 0
    kind, n, cmd = todo
    log("nothing indexed yet: the first index starts now, quick, newest first…" if kind == "first" else
        f"indexing {n:,} new from Photos…" if kind == "new" else f"redoing {n:,} quick first photos at full quality…")
    f = DATA / "index.log"
    start = f.stat().st_size if f.exists() else 0
    state.update(job=kind, since=time.time(), error=None)
    try:
        with open(f, "a") as out:
            r = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, preexec_fn=lambda: os.nice(10),
                               env=dict(os.environ, PHOTOSEARCH_STOP_WITH=str(os.getpid())))  # index.stop_with
    finally:
        state.update(job=None)
    if r.returncode == 0:
        log({"first": "the first index is done: every photo is in searches", "new": "indexed: they're in searches now",
             "redo": "redone: every photo is at full quality"}[kind])
    else:
        state["error"] = last_line(f, start) or f"`photosearch index` stopped (exit {r.returncode})"
        log(f"indexing stopped (exit {r.returncode}), tried again later; see {f}")
    return n if kind == "new" else 0


def progress(con):
    """For the page: how far indexing has got. job: "first", "new", "redo" or None; library: how many photos and
    videos Photos has (None until it can be read); error: why the last run stopped, with hint "access" if it
    couldn't read Photos."""
    one = lambda sql: con.execute(sql).fetchone()[0]
    lib = library_uuids()
    err = state["error"]
    return dict(job=state["job"], since=state["since"], photos=one("select count(*) from photos"),
                quick=one("select count(*) from photos where quick"), library=len(lib) if lib else None,
                error=err, hint="access" if err and NO_ACCESS.search(err) else None)


def start(log=print):
    """Index now and then, for as long as this process runs: at once if nothing is indexed yet."""
    def loop():
        con = db()
        time.sleep(0 if not index_library() else FIRST)
        while True:
            try:
                check(con, log)
            except Exception as ex:  # an unreadable library, say: try again next time
                log(f"looking for new photos: {ex.__class__.__name__}: {ex}")
            # a first index that couldn't start (no access to Photos yet, say) is tried again soon, not in 15 minutes
            time.sleep(FIRST if state["error"] and not index_library() else EVERY)
    threading.Thread(target=loop, daemon=True, name="new photos").start()
