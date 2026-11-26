"""A folder of photos as a library (folders.py): read through the same fields as Photos, by store.photos_db."""
import json, os, shutil, subprocess
from argparse import Namespace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image

from photosearch import folders, index, photos_app, store


def photo(path, when=None, offset=None, gps=None, color=(200, 120, 40), size=(64, 48)):
    """A small JPEG, with EXIF date (and time zone) and GPS if given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    exif = Image.Exif()
    if when:
        ifd = exif.get_ifd(0x8769)
        ifd[36867] = when
        if offset:
            ifd[36881] = offset
    if gps:
        (lat, ns), (lon, ew) = gps
        g = exif.get_ifd(0x8825)
        g.update({1: ns, 2: (float(lat), 0.0, 0.0), 3: ew, 4: (float(lon), 0.0, 0.0)})
    im.save(path, exif=exif)
    return path


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Pictures"
    photo(root / "beach.jpg", "2024:07:10 14:00:00", "-07:00", ((49, "N"), (123, "W")))
    photo(root / "Lisbon 2025" / "tram.jpg", "2025:03:11 09:30:00", "+00:00", color=(30, 90, 200))
    photo(root / "Lisbon 2025" / "zz tram copy.jpg", "2025:03:11 09:30:00", "+00:00", color=(30, 90, 200))  # the same file twice
    photo(root / "scan.jpg", color=(90, 90, 90))  # no EXIF: the file's date
    os.utime(root / "scan.jpg", (datetime(1998, 6, 1, 12).timestamp(),) * 2)
    photo(root / ".hidden" / "x.jpg", color=(1, 2, 3))
    photo(root / "Old.photoslibrary" / "originals" / "y.jpg", color=(4, 5, 6))
    (root / "notes.txt").write_text("not a photo")
    return root


def test_a_folder_is_read_like_photos(folder):
    lib = store.photos_db(str(folder))
    assert isinstance(lib, folders.Folder) and lib.library_path == str(folder.resolve())
    ps = {os.path.basename(p.path): p for p in lib.photos(intrash=False)}
    assert set(ps) == {"beach.jpg", "tram.jpg", "scan.jpg"}  # a copy counts once; hidden folders and Photos libraries don't
    b = ps["beach.jpg"]
    assert b.date == datetime(2024, 7, 10, 14, tzinfo=timezone(timedelta(hours=-7))) and b.location == (49.0, -123.0)
    assert b.isphoto and not b.ismovie and b.path_derivatives == [b.path] and b.albums == []
    assert ps["tram.jpg"].albums == ["Lisbon 2025"] and ps["tram.jpg"].location is None
    assert ps["scan.jpg"].date.year == 1998
    assert lib.get_photo(b.uuid) is b and lib.photos(uuid=[b.uuid, "NOPE"]) == [b]


def test_a_files_id_follows_its_content(folder):
    first = {p.uuid for p in store.photos_db(str(folder)).photos()}
    shutil.move(folder / "beach.jpg", folder / "Lisbon 2025" / "renamed.jpg")
    again = store.photos_db(str(folder)).photos()
    assert {p.uuid for p in again} == first
    assert next(p for p in again if p.path.endswith("renamed.jpg")).albums == ["Lisbon 2025"]


def test_rescans_read_only_new_files(folder, monkeypatch):
    store.photos_db(str(folder)).photos()
    read = []
    real = folders.image_meta
    monkeypatch.setattr(folders, "image_meta", lambda p: read.append(p.name) or real(p))
    photo(folder / "new.jpg", "2026:01:01 10:00:00", color=(10, 200, 10))
    assert len(store.photos_db(str(folder)).photos()) == 4 and read == ["new.jpg"]


def test_the_folder_changing_is_noticed(folder):
    before = folders.stamp(folder)
    photo(folder / "Lisbon 2025" / "another.jpg", color=(250, 250, 0))
    assert folders.stamp(folder) != before


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_videos_date_and_first_frame(folder):
    out = folder / "Clips" / "clip.mov"; out.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "color=c=red:s=64x48:d=1", "-metadata",
                    "creation_time=2023-05-06T07:08:09Z", str(out)], check=True)
    v = next(p for p in store.photos_db(str(folder)).photos() if p.ismovie)
    assert v.date == datetime(2023, 5, 6, 7, 8, 9, tzinfo=timezone.utc) and v.albums == ["Clips"]
    (frame,) = v.path_derivatives
    assert Image.open(frame).size == (64, 48)


def test_a_folder_indexes_end_to_end(lib, folder, monkeypatch):
    from test_index import Model
    c = store.db()
    for t in ("photos", "skipped", "meta"):
        c.execute(f"delete from {t}")
    c.commit(); c.close()
    m = Model(); m.proc.image_seq_length = 280
    monkeypatch.setattr(index.embed, "model", lambda audio=False: m)
    index.cmd_index(Namespace(library=str(folder), limit=None, batch=2, no_videos=True, quick=False, here=True))
    con = store.db()
    rows = {r[0][:10]: r for r in con.execute("select date, kind, albums, lat from photos")}
    assert set(rows) == {"2024-07-10", "2025-03-11", "1998-06-01"} and rows["2025-03-11"][2] == '["Lisbon 2025"]'
    assert rows["2024-07-10"][3] == 49.0
    assert store.index_library() == str(folder.resolve())
    # no Photos app or iCloud for a folder: its photos are their own full size, and albums stay in this app
    folders._in_use.clear()
    u = con.execute("select uuid from photos limit 1").fetchone()[0]
    assert not photos_app.needs_fetch(con, u)
    with pytest.raises(LookupError, match="folder"):
        photos_app.photos_only()
    folders._in_use.clear()


@pytest.fixture
def towns(tmp_path, monkeypatch):
    """A made-up list of towns in place of GeoNames' (no download)."""
    from photosearch import geonames
    monkeypatch.setattr(geonames, "CACHE", tmp_path / "geonames")
    monkeypatch.setattr(geonames, "_places", None)
    geonames.save([("Canmore", 51.089, -115.359, "Alberta", "Canada", 15990), ("Harvie Heights", 51.105, -115.395, "Alberta", "Canada", 1000),
                   ("Mexico City", 19.43, -99.13, "Mexico City", "Mexico", 12294193)])
    return geonames


def test_places_are_named_from_the_list_of_towns(towns):
    canmore, sea, mexico = towns.name([(51.100, -115.385), (40.0, -40.0), (19.43, -99.14)])
    # beside a village, but the town is about as near and much bigger: the town, as Photos would say
    assert canmore == dict(city="Canmore", state="Alberta", country="Canada", name="Canmore, Alberta, Canada")
    assert sea["city"] == "" and mexico["name"] == "Mexico City, Mexico"


def test_without_the_list_places_stay_unnamed(tmp_path, monkeypatch):
    from photosearch import geonames
    monkeypatch.setattr(geonames, "CACHE", tmp_path / "none")
    monkeypatch.setattr(geonames, "_places", None)
    monkeypatch.setattr(geonames, "download", lambda: (_ for _ in ()).throw(OSError("offline")))
    assert geonames.name([(51.1, -115.4)]) == [None]


def test_a_folders_places_labels_and_screenshots(folder, towns, monkeypatch):
    photo(folder / "canmore.jpg", "2024:08:01 10:00:00", gps=((51.100, "N"), (115.385, "W")), color=(0, 140, 0))
    Image.new("RGB", (60, 120), (255, 255, 255)).save(folder / "IMG_0001.PNG")  # no camera made it
    seen = []
    monkeypatch.setattr(folders, "classify", lambda path: seen.append(path) or ["Outdoor", "Grass"])
    ps = {os.path.basename(p.path): p for p in store.photos_db(str(folder)).photos()}
    assert ps["canmore.jpg"].place.name == "Canmore, Alberta, Canada" and ps["canmore.jpg"].place.names.city == ["Canmore"]
    assert ps["IMG_0001.PNG"].screenshot and not ps["canmore.jpg"].screenshot
    assert ps["canmore.jpg"].labels == ["Outdoor", "Grass"] and len(seen) == 1
    again = {os.path.basename(p.path): p for p in store.photos_db(str(folder)).photos()}
    assert again["canmore.jpg"].labels == ["Outdoor", "Grass"] and len(seen) == 1  # read once, then kept
    assert json.loads(index.geo(again["canmore.jpg"])) == dict(city="Canmore", state="Alberta", country="Canada")


def test_vision_reads_whats_in_a_photo(tmp_path):
    f = photo(tmp_path / "sky.jpg", color=(90, 160, 235), size=(400, 300))
    assert all(isinstance(x, str) and x == x.title() for x in folders.classify(f))  # what it sees in plain blue, if anything
