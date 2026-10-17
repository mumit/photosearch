"""`photosearch videos`: what's heard in each video, and what happens after its first frame. `photosearch index` embeds
only a video's poster frame; this adds a vector for every SOUND_WIN seconds of sound and a frame every FRAME_EVERY
seconds, so "people singing Happy Birthday" finds the video and the moment it happens.

Sound vectors land in the same space as text and images, but a noisy clip (a trampoline park, a stadium) is close to
every sound, so a sound counts by how much closer it is to the search than to SOUND_BASE, the everyday sounds of home
videos. Measured on 48 videos: a match stood out by +0.09 to +0.19 (Happy Birthday over a cake, laughing on a couch),
others by about 0. SOUND_AT was set by ear (data/sound-marks.json): at 0.59, the heard videos in the top 24 of 12
searches were 19 right and 6 wrong, all 6 "a dog barking" (kids shouting). At 0.62, wrong ones flooded in.

Most videos live only in iCloud. With --icloud they're downloaded through PhotoKit (~2 s each), which leaves the
original in the Photos library as `photosearch fetch` does; nothing in the library changes. Only frames are kept here.
"""
import shutil, subprocess, tempfile, time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import embed
from .config import DATA, DIM, THUMB_PX

FRAMES = DATA / "frames"  # FRAMES/<uuid>/<seconds>.jpg, for showing the moment
FRAME_EVERY = 3  # seconds between frames
FRAME_EMBED_PX = 768  # what the model sees of a frame; the kept copy is THUMB_PX
SOUND_WIN = 10  # seconds of sound per vector, so a long video says when
RATE = 16000  # the model wants mono 16 kHz
SOUND_AT = 0.59
SOUND_BASE = ["people talking", "background noise", "a room", "voices", "a sound", "someone speaking",
              "noise outdoors", "a video"]


def forget(con, uuid):
    """A video gone from the library: its moments go too."""
    con.execute("delete from clips where uuid=?", (uuid,))
    con.execute("delete from videos_done where uuid=?", (uuid,))
    shutil.rmtree(FRAMES / uuid, ignore_errors=True)


def sound_of(path):
    """Mono 16 kHz samples as float32 in [-1, 1]; empty if the video has no sound."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768


def frames_of(path):
    """[(seconds, image)], a frame every FRAME_EVERY seconds from the start."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                        f"fps=1/{FRAME_EVERY}:start_time=0:round=down:eof_action=pass,scale={FRAME_EMBED_PX}:{FRAME_EMBED_PX}:force_original_aspect_ratio=decrease",
                        "-q:v", "3", f"{tmp}/%05d.jpg"], check=True)
        out = []
        for i, f in enumerate(sorted(Path(tmp).glob("*.jpg"))):
            im = Image.open(f); im.load(); out.append((i * FRAME_EVERY, im.convert("RGB")))
        return out


def windows(x):
    """[(seconds, samples)]: SOUND_WIN-second pieces; a last piece under 2 s joins the one before."""
    n = SOUND_WIN * RATE
    if len(x) < RATE or np.abs(x).max() < 1e-4:  # under a second, or silent
        return []
    out = [(i // RATE, x[i:i + n]) for i in range(0, len(x), n)]
    if len(out) > 1 and len(out[-1][1]) < 2 * RATE:
        t, last = out.pop(); out[-1] = (out[-1][0], np.concatenate([out[-1][1], last]))
    return out


def embed_video(con, uuid, path):
    """Embeds one video's frames and sound into clips, and keeps its frames. Returns (frames, sounds)."""
    m = embed.model(audio=True)
    fr, so = frames_of(path), windows(sound_of(path))
    rows = []
    if fr:
        V = m.encode([im for _, im in fr], batch_size=8, normalize_embeddings=True).astype(np.float32)
        d = FRAMES / uuid; d.mkdir(parents=True, exist_ok=True)
        for (t, im), v in zip(fr, V):
            im.thumbnail((THUMB_PX, THUMB_PX)); im.save(d / f"{t}.jpg", quality=80)
            rows.append((uuid, "frame", t, v.tobytes()))
    if so:
        V = m.encode([{"audio": {"array": x, "sampling_rate": RATE}} for _, x in so], batch_size=4,
                     normalize_embeddings=True).astype(np.float32)
        rows += [(uuid, "sound", t, v.tobytes()) for (t, _), v in zip(so, V)]
    con.execute("delete from clips where uuid=?", (uuid,))
    con.executemany("insert into clips values(?,?,?,?)", rows)
    return len(fr), len(so)


def local_file(p):
    """The video as shown in Photos (edited if it was), if it's on this Mac."""
    for f in ([p.path_edited] if p.hasadjustments else []) + [p.path]:
        if f and Path(f).exists():
            return f
    return None


VIDEO_FILES = (".mov", ".mp4", ".m4v", ".3gp", ".3g2", ".avi", ".mpg", ".mts")  # 3gp: 2010 phones
DOWNLOAD_BATCH = 25  # videos per downloading process; each holds at most this many files at once


def downloads(uuids, tmp):
    """Yields (uuid, file or None, error) as a `photosearch download-videos` process gets each from iCloud, so one
    video can be embedded while the next downloads. PhotoKit runs in its own process, so a crash (pyobjc segfaulted
    on edited videos) only loses the video it was on, which is tried again next run."""
    import sys
    queue = list(uuids)
    while queue:
        batch, queue, seen = queue[:DOWNLOAD_BATCH], queue[DOWNLOAD_BATCH:], set()
        proc = subprocess.Popen([sys.executable, "-m", "photosearch", "download-videos", tmp, *batch],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in proc.stdout:
            u, _, rest = line.rstrip("\n").partition(" ")
            if u in batch and u not in seen:
                seen.add(u)
                yield (u, rest[3:], None) if rest.startswith("ok ") else (u, None, rest)
        proc.wait()
        left = [u for u in batch if u not in seen]
        if left:  # it crashed on the first of these; the others go to a new process
            yield left[0], None, f"the download process stopped (exit {proc.returncode})"
            queue = left[1:] + queue


def cmd_download_videos(a):
    """For `downloads`: each video from iCloud into a.dir, printing "UUID ok PATH" or "UUID ERROR" as it goes."""
    from osxphotos import ExportOptions, PhotoExporter
    from .store import photos_db
    pdb = photos_db()
    for u in a.uuids:
        p = pdb.get_photo(u)
        try:
            d = Path(a.dir) / u; d.mkdir(parents=True, exist_ok=True)
            # the original, even of an edited video: PhotoKit rendering an edit crashed the process every time
            r = PhotoExporter(p).export(str(d), options=ExportOptions(download_missing=True, use_photokit=True,
                                                                      edited=False, timeout=300))
            f = [x for x in r.exported if Path(x).suffix.lower() in VIDEO_FILES]
            print(f"{u} ok {f[0]}" if f else f"{u} {r.error or 'nothing exported'} {[Path(x).name for x in r.exported]}", flush=True)
        except Exception as ex:
            print(f"{u} {ex.__class__.__name__}: {ex}"[:300], flush=True)


def embed_videos(con, pdb, icloud=False, limit=None):
    """Reads every video not done yet, newest first. Without icloud, only those already on this Mac; the rest wait
    for `photosearch videos --icloud`. A video that couldn't be read is tried again next time."""
    if not shutil.which("ffmpeg"):
        print("videos: skipped, ffmpeg isn't installed (brew install ffmpeg)")
        return
    done = {r[0] for r in con.execute("select uuid from videos_done where error is null")}
    todo = [r[0] for r in con.execute("select uuid from photos where kind='video' order by date desc") if r[0] not in done]
    todo = todo[:limit] if limit else todo
    print(f"videos: {len(done)} done, {len(todo)} to go", flush=True)
    t0, n = time.time(), 0

    def read(u, f, err):
        nonlocal n
        nf = ns = 0
        if f:
            try:
                nf, ns = embed_video(con, u, f)
            except Exception as ex:  # ffmpeg can't read it: try again next time
                err = f"{ex.__class__.__name__}: {ex}"[:300]
        if err:
            print(f"\n  couldn't read {u}: {err}")
        con.execute("insert or replace into videos_done values(?,?,?,?,?)", (u, nf, ns, err, datetime.now().isoformat()))
        con.commit(); n += 1
        print(f"\r{n} read  {(time.time() - t0) / n:.1f} s each   ", end="", flush=True)

    photos = {u: p for u in todo if (p := pdb.get_photo(u))}
    here = {u: f for u, p in photos.items() if (f := local_file(p))}
    for u, f in here.items():
        read(u, f, None)
    away = [u for u in photos if u not in here]
    if icloud and away:
        with tempfile.TemporaryDirectory() as tmp:
            for u, f, err in downloads(away, tmp):
                read(u, f, err)
                shutil.rmtree(Path(tmp) / u, ignore_errors=True)
    if todo:
        print(f"\nvideos: {n} read in {(time.time() - t0) / 60:.1f} min"
              + (f"; {len(away)} are only in iCloud (`photosearch videos --icloud` downloads them)" if away and not icloud else ""))


def cmd_videos(a):
    from .index import check_settings
    from .store import db, photos_db
    con = db(); check_settings(con)
    embed_videos(con, photos_db(), a.icloud, a.limit)


_clips = (None,)

def clips(con):
    """Every moment's vector, grouped by video: (uuids, starts, kinds, seconds, vectors, base), reloaded when clips
    change. base is how close each sound is to everyday sounds (SOUND_BASE)."""
    global _clips
    stamp = con.execute("select count(*), max(rowid) from clips").fetchone()
    if _clips[0] != stamp:
        rows = con.execute("select uuid, kind, t, vec from clips order by uuid, kind, t").fetchall()
        C = np.stack([np.frombuffer(r[3], np.float32) for r in rows]) if rows else np.zeros((0, DIM), np.float32)
        owner = [r[0] for r in rows]
        starts = [i for i in range(len(rows)) if i == 0 or owner[i] != owner[i - 1]]
        sound = np.array([r[1] == "sound" for r in rows], bool)
        B = np.stack([embed.embed_query(t) for t in SOUND_BASE])
        base = (C @ B.T).mean(1) if rows else np.zeros(0, np.float32)
        _clips = (stamp, [owner[i] for i in starts], np.array(starts, int), sound,
                  np.array([r[2] for r in rows], float), C, base)
    return _clips[1:]


def moments(con, q, sounds=True):
    """{uuid: (score, seconds, heard, frame)}: each video's best moment for the query vector q, and the kept frame
    that shows it (for a sound, the one nearest its middle). Sounds only for words: a photo isn't heard."""
    uuids, starts, sound, t, C, base = clips(con)
    if not uuids:
        return {}
    s = C @ q
    s = np.where(sound, s - base + SOUND_AT, s) if sounds else np.where(sound, -np.inf, s)
    out = {}
    for u, a, b in zip(uuids, starts, list(starts[1:]) + [len(s)]):
        i = a + int(np.argmax(s[a:b]))
        fr = [x for x in range(a, b) if not sound[x]]
        mid = t[i] + SOUND_WIN / 2 if sound[i] else t[i]
        f = int(t[min(fr, key=lambda x: abs(t[x] - mid))]) if fr else None
        out[u] = (float(s[i]), float(t[i]), bool(sound[i]), f)
    return out


def frame_list(con, uuid):
    """The seconds at which a video has a kept frame, for flipping through it."""
    return [int(r[0]) for r in con.execute("select t from clips where uuid=? and kind='frame' order by t", (uuid,))
            if (FRAMES / uuid / f"{int(r[0])}.jpg").exists()]
