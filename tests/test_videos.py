"""Videos found by what's heard in them and by their later frames (`photosearch videos`), with the moment shown."""
import shutil, subprocess

import numpy as np
import pytest

import library
from photosearch import embed, search, videos
from server import Server


def clip(con, uuid, kind, t, v):
    con.execute("insert into clips values(?,?,?,?)", (uuid, kind, t, library.unit(v).tobytes())); con.commit()


def test_sound_comes_in_pieces_and_silence_is_skipped():
    s = lambda sec: np.full(int(sec * videos.RATE), 0.1, np.float32)
    assert [t for t, _ in videos.windows(s(25))] == [0, 10, 20]
    w = videos.windows(s(21))  # the last second joins the piece before
    assert [t for t, _ in w] == [0, 10] and len(w[-1][1]) == 11 * videos.RATE
    assert videos.windows(s(0.5)) == [] and videos.windows(np.zeros(5 * videos.RATE, np.float32)) == []


def test_a_video_is_found_by_what_is_heard(con, lib):
    clip(con, lib["video"], "frame", 0, library.axis("dog"))
    clip(con, lib["video"], "frame", 12, library.axis("dog"))
    clip(con, lib["video"], "sound", 10, library.axis("cake"))  # someone sings Happy Birthday off camera
    first = search.search(con, "a birthday")[0]
    assert first["uuid"] == lib["video"]
    assert (first["at"], first["heard"], first["frame"]) == (10, True, 12)  # the frame nearest the sound's middle
    assert lib["video"] not in {r["uuid"] for r in search.search(con, "a birthday", kind="photo")}
    # a photo isn't heard: looking for photos like a cake doesn't bring up the singing
    assert not any(r.get("heard") for r in search.similar(con, lib["cake0"]))


def test_a_later_frame_finds_a_video_and_says_when(con, lib):
    clip(con, lib["video"], "frame", 0, library.axis("dog"))
    clip(con, lib["video"], "frame", 6, library.axis("snow"))
    r = {x["uuid"]: x for x in search.search(con, "snow", k=100)}[lib["video"]]
    assert (r["at"], r["heard"], r["frame"]) == (6, False, 6)
    r = {x["uuid"]: x for x in search.search(con, "a dog", k=100)}[lib["video"]]
    assert "at" not in r  # the poster frame already shows it


def test_the_page_gets_a_videos_frames(con, lib):
    clip(con, lib["video"], "frame", 0, library.axis("dog")); clip(con, lib["video"], "frame", 3, library.axis("dog"))
    d = videos.FRAMES / lib["video"]; d.mkdir(parents=True)
    for t in (0, 3):
        (d / f"{t}.jpg").write_bytes(b"\xff\xd8 frame")
    srv = Server()
    try:
        assert srv.json(f"/api/frames?uuid={lib['video']}") == [0, 3]
        assert srv.get(f"/frame/{lib['video']}/3.jpg")[0] == 200
        assert srv.get(f"/frame/{lib['video']}/4.jpg")[0] == 404
        assert srv.get("/frame/..%2F..%2Findex.sqlite/1.jpg")[0] == 404
    finally:
        srv.close()
    videos.forget(con, lib["video"])
    assert not d.exists() and videos.frame_list(con, lib["video"]) == []


class Hears:
    """Stands in for the model: every frame looks like a beach, and every sound like a birthday."""
    def encode(self, xs, **kw):
        return np.stack([library.axis("cake" if isinstance(x, dict) else "beach") for x in xs])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_video_file_becomes_frames_and_sound(con, lib, monkeypatch, tmp_path):
    f = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=7:s=320x240:r=10", "-f", "lavfi", "-i",
                    "sine=f=440:d=7", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(f)], check=True)
    monkeypatch.setattr(embed, "model", lambda audio=False: Hears())
    assert videos.embed_video(con, lib["video"], f) == (3, 1)  # frames at 0, 3 and 6 s; one piece of sound
    assert videos.frame_list(con, lib["video"]) == [0, 3, 6]
    first = search.search(con, "a birthday")[0]
    assert first["uuid"] == lib["video"] and first["heard"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_index_reads_new_videos_on_this_mac_and_leaves_icloud_ones(con, lib, monkeypatch, tmp_path):
    from types import SimpleNamespace
    f = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=4:s=320x240:r=10", "-f", "lavfi", "-i",
                    "sine=f=440:d=4", "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(f)], check=True)
    away = lib["dog0"]
    con.execute("update photos set kind='video' where uuid=?", (away,)); con.commit()
    here = SimpleNamespace(hasadjustments=False, path=str(f), path_edited=None)
    cloud = SimpleNamespace(hasadjustments=False, path=None, path_edited=None)
    pdb = SimpleNamespace(get_photo=lambda u: here if u == lib["video"] else cloud)
    monkeypatch.setattr(embed, "model", lambda audio=False: Hears())
    videos.embed_videos(con, pdb)  # no icloud: nothing is downloaded
    done = dict(con.execute("select uuid, frames from videos_done").fetchall())
    assert done == {lib["video"]: 2}  # the iCloud one waits for `photosearch videos --icloud`
    videos.embed_videos(con, pdb)
    assert con.execute("select count(*) from videos_done").fetchone()[0] == 1  # and the done one isn't read again
