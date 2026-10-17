"""`photosearch videos`: what's heard in each video, and what happens after its first frame. `photosearch index` embeds
only a video's poster frame; this adds a vector for every SOUND_WIN seconds of sound and a frame every FRAME_EVERY
seconds, so "people singing Happy Birthday" finds the video and the moment it happens.

Sound vectors land in the same space as text and images, but a noisy clip (a trampoline park, a stadium) is close to
every sound, so a sound counts by how much closer it is to the search than to SOUND_BASE, the everyday sounds of home
videos. Measured on 48 videos: a match stood out by +0.09 to +0.19 (Happy Birthday over a cake, laughing on a couch),
others by about 0. SOUND_AT puts a +0.06 sound about where the best 0.1% of photos are.

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
SOUND_AT = 0.62
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


def video_file(p, tmp, icloud):
    """The video as shown in Photos (edited if it was), on disk: local, or downloaded into tmp with icloud."""
    for f in ([p.path_edited] if p.hasadjustments else []) + [p.path]:
        if f and Path(f).exists():
            return f
    if not icloud:
        return None
    from osxphotos import ExportOptions, PhotoExporter
    r = PhotoExporter(p).export(tmp, options=ExportOptions(download_missing=True, use_photokit=True,
                                                           edited=p.hasadjustments, timeout=300))
    f = [x for x in r.exported if Path(x).suffix.lower() in (".mov", ".mp4", ".m4v")]
    if not f:
        raise RuntimeError(r.error or "nothing exported")
    return f[0]


def embed_videos(con, pdb, icloud=False, limit=None):
    """Reads every video not done yet, newest first. Without icloud, only those already on this Mac; the rest wait
    for `photosearch videos --icloud`. A video that couldn't be read is tried again next time."""
    if not shutil.which("ffmpeg"):
        print("videos: skipped, ffmpeg isn't installed (brew install ffmpeg)")
        return
    done = {r[0] for r in con.execute("select uuid from videos_done where error is null")}
    todo = [r[0] for r in con.execute("select uuid from photos where kind='video' order by date desc") if r[0] not in done]
    print(f"videos: {len(done)} done, {len(todo)} to go", flush=True)
    t0, n, away = time.time(), 0, 0
    for u in todo[:limit] if limit else todo:
        p = pdb.get_photo(u)
        if not p:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                f = video_file(p, tmp, icloud)
                if not f:
                    away += 1; continue
                nf, ns = embed_video(con, u, f); err = None
            except Exception as ex:  # offline, iCloud says no, or ffmpeg can't read it: try again next time
                nf = ns = 0; err = f"{ex.__class__.__name__}: {ex}"[:300]
                print(f"\n  couldn't read {u}: {err}")
        con.execute("insert or replace into videos_done values(?,?,?,?,?)", (u, nf, ns, err, datetime.now().isoformat()))
        con.commit(); n += 1
        print(f"\r{n} read  {(time.time() - t0) / n:.1f} s each   ", end="", flush=True)
    if todo:
        print(f"\nvideos: {n} read in {(time.time() - t0) / 60:.1f} min"
              + (f"; {away} are only in iCloud (`photosearch videos --icloud` downloads them)" if away else ""))


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
