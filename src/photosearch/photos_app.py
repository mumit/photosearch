"""Everything that talks to the Photos app or iCloud: adding to albums, fetching full-size copies.

Both run in a separate `photosearch` process: Photos automation and PhotoKit want a main thread."""
import re, sys, threading
from pathlib import Path

from .config import DISPLAY_PX, LARGE, SHARP_PX, THUMBS, THUMB_PX
from .store import db, photos_db
from .images import open_image
from .stories import STORY_ID, load_review, story_uuids


def add_to_photos_album(name, uuids):
    """Add photos to an album in the Photos app (made if needed), in a `photosearch add-to-album` process: Photos is driven
    by AppleScript, which is happiest on a process's main thread. Only ever adds. Returns how many were added."""
    import subprocess
    uuids = list(dict.fromkeys(uuids))
    if not uuids:
        return 0
    r = subprocess.run([sys.executable, "-m", "photosearch", "add-to-album", name, *uuids], capture_output=True, text=True,
                       timeout=120 + len(uuids))
    m = re.search(r"added (\d+)", r.stdout)
    if r.returncode or not m:
        raise LookupError("Photos didn't take them: " + (r.stderr.strip().splitlines() or ["no reply"])[-1][:200])
    return int(m.group(1))


def cmd_add_to_album(a):
    from osxphotos.photosalbum import PhotosAlbum
    order = {u: i for i, u in enumerate(a.uuids)}
    photos = sorted(photos_db().photos(uuid=list(order)), key=lambda p: order[p.uuid])
    PhotosAlbum(a.name).add_list(photos)
    print(f"added {len(photos)} photos to album '{a.name}'")


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
    """fetch_large in a `photosearch fetch` process. PhotoKit hangs on its second request when its first came from a
    worker thread (seen with the web server's), so fetches run on a process's main thread, which can also be
    killed if iCloud stalls. Returns the uuids still needing a fetch afterwards (all of them if not waiting)."""
    import subprocess
    todo = [u for u in dict.fromkeys(uuids) if needs_fetch(con, u)]
    if not todo:
        return []
    cmd = [sys.executable, "-m", "photosearch", "fetch", *todo]
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


def cmd_fetch(a):
    """Full-size copies from iCloud for photos (uuids) or every photo in stories (2025, trip-2024-05-02)."""
    con = db()
    uuids = [u for x in a.what for u in (story_uuids(load_review(con, x, make=True)) if STORY_ID.fullmatch(x) else [x])]
    need = [u for u in dict.fromkeys(uuids) if needs_fetch(con, u)]
    print(f"{len(uuids)} photos, {len(need)} need a full-size copy")
    print(f"fetched {fetch_large(con, need, log=print)}")
