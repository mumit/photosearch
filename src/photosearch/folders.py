"""A folder of photos as a library, for photos that aren't in Apple Photos: a drive of scans, Lightroom's folders, a
Google Photos export. `photosearch index --library FOLDER` records it as the data folder's library, and from then
on every command reads it the way they read Photos: `Folder` and `File` answer with the few fields of osxphotos'
PhotosDB and PhotoInfo the app uses (store.photos_db picks the kind), so little else needs to know.

Every image and video under the folder counts, but not inside a Photos library or a hidden folder. A file's id comes
from its content (its size and its first and last 64 KB), so moving or renaming one keeps it in the index, and two
copies of a file count once. The date comes from EXIF (with its time zone), a video's from its own tags, else the
file's date; the place from EXIF GPS, named by geonames.py; its albums are the folder it's in; what's in it from
Apple's Vision (LABEL_AT); screenshots are PNGs no camera made, selfies those from a front camera. Mac only: Apple's
ImageIO reads each file's metadata and makes previews of what Pillow can't open (RAW). What's been read is kept in
FILES (by path, size and time, so a later scan only reads new and changed files), a database of its own so it never
waits on `index` writing the index."""
import json, os, re, subprocess, uuid as uuidlib
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path

from .config import DATA

PREVIEWS = DATA / "previews"  # for files Pillow can't read: RAW photos, and videos' first frames
FILES = DATA / "folder.sqlite"  # what's been read from each file, and Vision's labels
PILLOW = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".webp", ".gif", ".bmp"}
RAW = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}
VIDEOS = {".mov", ".mp4", ".m4v", ".3gp", ".3g2", ".avi", ".mpg", ".mts", ".mkv"}
CHUNK = 64 * 1024
LABEL_AT = 0.3  # Vision's confidence for a label: about as many a photo as Photos gives, and most the same (FINDINGS.md)


def is_folder(library):
    """Whether a library path is a folder of photos, not a Photos library (which has its database inside)."""
    p = Path(library)
    return p.is_dir() and p.suffix != ".photoslibrary" and not (p / "database" / "Photos.sqlite").exists()


_in_use = {}


def in_use():
    """Whether this data folder's index is of a folder of photos (so there's no Photos app or iCloud to ask)."""
    if DATA not in _in_use:
        from .store import index_library
        if (lib := index_library()) is None:
            return False  # no index yet: don't remember, the first index records which
        _in_use[DATA] = is_folder(lib)
    return _in_use[DATA]


def walk(root):
    """os.walk, leaving out hidden folders (and NAS ones: @eaDir, $RECYCLE.BIN), Photos libraries, and the albums
    this app makes as folders of links."""
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith((".", "@", "$")) and not x.endswith(".photoslibrary")
                         and x != "Photosearch albums")
        yield d, names


def files(root):
    """Every photo and video file under root."""
    for d, names in walk(root):
        for n in sorted(names):
            if not n.startswith(".") and Path(n).suffix.lower() in PILLOW | RAW | VIDEOS:
                yield Path(d) / n


def stamp(root):
    """Changes when a file is added to or removed from any folder under root (each folder's time), for
    store.library_uuids to know when to read the folder again."""
    return tuple(os.stat(d).st_mtime_ns for d, _ in walk(root))


def file_id(path, size):
    """An id in the form of Photos' uuids, from the file's size and its first and last 64 KB."""
    h = sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(CHUNK))
        if size > 2 * CHUNK:
            f.seek(-CHUNK, os.SEEK_END); h.update(f.read(CHUNK))
    return str(uuidlib.UUID(bytes=h.digest()[:16])).upper()


def image_meta(path):
    """(date, (lat, lon) or None, width, height, flags) from a photo's metadata, read by ImageIO (any format, RAW too).
    flags: "screenshot" for a PNG with no camera's make, "selfie" for a front camera's."""
    import Quartz
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    props = src and Quartz.CGImageSourceCopyPropertiesAtIndex(src, 0, None)
    if not props:
        return None, None, 0, 0, []
    exif, tiff, gps, aux = (props.get(k) or {} for k in ("{Exif}", "{TIFF}", "{GPS}", "{ExifAux}"))
    date = exif_date(exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or tiff.get("DateTime"),
                     exif.get("OffsetTimeOriginal") or exif.get("OffsetTime"))
    where = None
    if gps.get("Latitude") is not None and gps.get("Longitude") is not None:
        where = (float(gps["Latitude"]) * (-1 if gps.get("LatitudeRef") == "S" else 1),
                 float(gps["Longitude"]) * (-1 if gps.get("LongitudeRef") == "W" else 1))
    w, h = int(props.get("PixelWidth") or 0), int(props.get("PixelHeight") or 0)
    if int(props.get("Orientation") or 1) in (5, 6, 7, 8):
        w, h = h, w
    lens = str(exif.get("LensModel") or aux.get("LensModel") or "").lower()
    flags = (["screenshot"] if Path(path).suffix.lower() == ".png" and not tiff.get("Make") else []) + \
            (["selfie"] if "front" in lens else [])
    return date, where, w, h, flags


def exif_date(text, offset=None):
    """"2022:04:16 14:54:48" and "-07:00" as a datetime, in this Mac's time zone if EXIF doesn't say; None if unreadable."""
    try:
        d = datetime.strptime(str(text).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    if offset:
        try:
            sign, hh, mm = (-1 if offset[0] == "-" else 1), int(offset[1:3]), int(offset[4:6])
            return d.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm)))
        except (ValueError, IndexError):
            pass
    return d.astimezone()


def video_meta(path):
    """(date, (lat, lon) or None) from a video's own tags, through ffprobe; (None, None) without it."""
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
                           capture_output=True, text=True, timeout=30)
        tags = json.loads(r.stdout or "{}").get("format", {}).get("tags", {})
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None, None
    date = None
    for k in ("com.apple.quicktime.creationdate", "creation_time"):  # the first has the local time and its offset
        if v := tags.get(k):
            try:
                date = datetime.fromisoformat(v.replace("Z", "+00:00"))
                date = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
    where = None
    if m := re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", tags.get("com.apple.quicktime.location.ISO6709", tags.get("location", ""))):
        where = (float(m.group(1)), float(m.group(2)))
    return date, where


def preview(path, uid, video):
    """A JPEG preview of a file Pillow can't read: ImageIO's for a RAW photo, the first frame of a video (ffmpeg).
    Made once, kept in PREVIEWS; None if it can't be made."""
    out = PREVIEWS / f"{uid}.jpg"
    if out.exists():
        return str(out)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".part.jpg")
    try:
        if video:
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", "0.5", "-i", str(path), "-frames:v", "1", "-vf",
                            "scale='min(2048,iw)':-2", str(part)], timeout=60, check=True)
        else:
            import Quartz
            from Foundation import NSURL
            src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
            opts = {Quartz.kCGImageSourceCreateThumbnailFromImageAlways: True, Quartz.kCGImageSourceThumbnailMaxPixelSize: 2048,
                    Quartz.kCGImageSourceCreateThumbnailWithTransform: True}
            im = src and Quartz.CGImageSourceCreateThumbnailAtIndex(src, 0, opts)
            dest = im and Quartz.CGImageDestinationCreateWithURL(NSURL.fileURLWithPath_(str(part)), "public.jpeg", 1, None)
            if not dest:
                return None
            Quartz.CGImageDestinationAddImage(dest, im, {Quartz.kCGImageDestinationLossyCompressionQuality: 0.88})
            if not Quartz.CGImageDestinationFinalize(dest):
                return None
        part.rename(out)
        return str(out)
    except (OSError, subprocess.SubprocessError):
        part.unlink(missing_ok=True)
        return None


def files_db():
    import sqlite3
    con = sqlite3.connect(FILES, timeout=30)
    con.execute("pragma journal_mode=wal")
    con.execute("create table if not exists files(path text primary key, size int, mtime int, uuid text, meta text)")
    con.execute("create table if not exists labels(uuid text primary key, labels text)")
    return con


def classify(path):
    """What Apple's Vision sees in a photo, as Photos' labels look ("Blue Sky"), at LABEL_AT or more; [] if it can't."""
    import Vision
    from Foundation import NSURL
    h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
    req = Vision.VNClassifyImageRequest.alloc().init()
    ok, _ = h.performRequests_error_([req], None)
    return [o.identifier().replace("_", " ").title() for o in (req.results() or []) if o.confidence() >= LABEL_AT] if ok else []


def place_info(p):
    """A place from geonames.name as osxphotos' PlaceInfo looks to index.geo and index.meta."""
    from types import SimpleNamespace
    one = lambda x: [x] if x else []
    return SimpleNamespace(name=p["name"], names=SimpleNamespace(
        city=one(p["city"]), sub_administrative_area=[], state_province=one(p["state"]), country=one(p["country"]),
        body_of_water=[], ocean=[], inland_water=[]))


class File:
    """One photo or video in a folder, with the fields of osxphotos' PhotoInfo the app reads."""
    title, persons, face_info, hasadjustments, path_edited = "", [], [], False, None

    def __init__(self, path, uid, date, where, root, flags=(), labels=None):
        self.path, self.uuid, self.date, self.location = str(path), uid, date, where
        self.ismovie = Path(path).suffix.lower() in VIDEOS
        self.isphoto = not self.ismovie
        rel = Path(path).relative_to(root).parent
        self.albums = [rel.name] if rel.parts else []
        self.screenshot, self.selfie = "screenshot" in flags, "selfie" in flags
        self.place, self._labels = None, labels

    @property
    def labels(self):
        """What's in it, from Vision: read once, then kept in FILES."""
        if self._labels is None:
            src = (self.path_derivatives or [None])[0]
            self._labels = classify(src) if src else []
            con = files_db()
            con.execute("insert or replace into labels values(?,?)", (self.uuid, json.dumps(self._labels)))
            con.commit(); con.close()
        return self._labels

    @property
    def path_derivatives(self):
        """What `index` reads: the file itself if Pillow can, else a preview made from it (best_local_image)."""
        if self.isphoto and Path(self.path).suffix.lower() in PILLOW:
            return [self.path]
        p = preview(self.path, self.uuid, self.ismovie)
        return [p] if p else []


class Folder:
    """A folder of photos, with the fields of osxphotos' PhotosDB the app reads."""
    def __init__(self, root):
        self.library_path = str(Path(root).resolve())
        self._files = None

    def _read(self):
        """{uuid: File}, reading only files that are new or changed since the last scan."""
        con = files_db()
        known = {p: (s, m, u, meta) for p, s, m, u, meta in con.execute("select * from files")}
        labels = {u: json.loads(ls) for u, ls in con.execute("select * from labels")}
        out, seen, new = {}, set(), []
        for f in files(self.library_path):
            try:
                st = f.stat()
            except OSError:
                continue
            k = str(f); seen.add(k)
            if k in known and known[k][:2] == (st.st_size, st.st_mtime_ns):
                uid, meta = known[k][2], json.loads(known[k][3])
            else:
                try:
                    uid = file_id(f, st.st_size)
                except OSError:
                    continue
                video = f.suffix.lower() in VIDEOS
                date, where, *_, flags = (*video_meta(f), []) if video else image_meta(f)
                date = date or datetime.fromtimestamp(st.st_mtime).astimezone()
                meta = dict(date=date.isoformat(), where=where, flags=flags)
                new.append((k, st.st_size, st.st_mtime_ns, uid, json.dumps(meta)))
            if uid not in out:  # a copy of a file already found counts once
                out[uid] = File(f, uid, datetime.fromisoformat(meta["date"]), tuple(meta["where"]) if meta["where"] else None,
                                self.library_path, meta.get("flags", []), labels.get(uid))
        con.executemany("insert or replace into files values(?,?,?,?,?)", new)
        con.executemany("delete from files where path=?", [(p,) for p in known if p not in seen])
        con.commit(); con.close()
        from . import geonames
        located = [x for x in out.values() if x.location]
        for x, p in zip(located, geonames.name([x.location for x in located])):
            x.place = p and place_info(p)
        self._files = out
        return out

    def photos(self, intrash=False, uuid=None):
        fs = self._files if self._files is not None else self._read()
        return [fs[u] for u in uuid if u in fs] if uuid is not None else list(fs.values())

    def get_photo(self, uuid):
        fs = self._files if self._files is not None else self._read()
        return fs.get(uuid)
