"""Adding to albums in the Photos app, with stand-ins for osxphotos (reads the library) and photoscript (drives Photos):
only ever into the library this index was built from, and only when Photos has that library open."""
import sys, types
from argparse import Namespace

import pytest

from photosearch import cli, photos_app, store


class FakePhotos:
    """indexed: the uuids in this index's library. open_has: the uuids in the library Photos has open."""
    def __init__(self, monkeypatch, indexed, open_has, library="/Users/x/Pictures/Photosearch Demo.photoslibrary"):
        self.albums, self.opened = {}, []
        fake = self

        class PhotosDB:
            def __init__(self, dbfile=None):
                fake.opened.append(dbfile)
                self.library_path = dbfile or library

            def photos(self, uuid=()):
                return [types.SimpleNamespace(uuid=u) for u in uuid if u in indexed]

        class PhotosAlbum:
            def __init__(self, name):
                fake.albums.setdefault(name, [])  # the real one makes the album here, before adding
                self.name = name

            def add_list(self, photos):
                fake.albums[self.name] += [p.uuid for p in photos]

        def Photo(uuid):
            if uuid not in open_has:
                raise ValueError(f"Invalid photo id: {uuid}")

        osxphotos = types.ModuleType("osxphotos"); osxphotos.PhotosDB = PhotosDB
        album = types.ModuleType("osxphotos.photosalbum"); album.PhotosAlbum = PhotosAlbum
        photoscript = types.ModuleType("photoscript"); photoscript.Photo = Photo
        for name, mod in (("osxphotos", osxphotos), ("osxphotos.photosalbum", album), ("photoscript", photoscript)):
            monkeypatch.setitem(sys.modules, name, mod)


def test_adds_when_photos_has_the_right_library_open(lib, monkeypatch):
    ids = [lib["beach0"], lib["beach1"], lib["dog0"]]
    fake = FakePhotos(monkeypatch, indexed=set(ids), open_has=set(ids))
    assert photos_app.add_now("Summer", [ids[2], ids[0], ids[1], ids[0]]) == 3
    assert fake.albums == {"Summer": [ids[2], ids[0], ids[1]]}  # in the order given, once each


def test_refuses_before_making_an_album_when_another_library_is_open(lib, monkeypatch):
    ids = [lib["beach0"], lib["beach1"]]
    fake = FakePhotos(monkeypatch, indexed=set(ids), open_has=set())  # e.g. your own library, during a demo
    with pytest.raises(LookupError, match="another library.*Photosearch Demo.*Nothing was added"):
        photos_app.add_now("Summer", ids)
    assert fake.albums == {}


def test_photos_not_in_the_library_add_nothing(monkeypatch):
    fake = FakePhotos(monkeypatch, indexed=set(), open_has=set())
    assert photos_app.add_now("Summer", ["0000-NOT-THERE"]) == 0 and fake.albums == {}


def test_each_index_reads_its_own_library(con, monkeypatch):
    fake = FakePhotos(monkeypatch, indexed=set(), open_has=set())
    store.photos_db()
    con.execute("insert into meta values('library', '/Volumes/Demo/Photosearch Demo.photoslibrary')"); con.commit()
    store.photos_db()
    store.photos_db("/elsewhere.photoslibrary")  # asked for by name: that one
    assert fake.opened == [None, "/Volumes/Demo/Photosearch Demo.photoslibrary", "/elsewhere.photoslibrary"]


def test_the_cli_goes_through_the_check(lib, monkeypatch):
    fake = FakePhotos(monkeypatch, indexed=set(lib.values()), open_has=set())
    with pytest.raises(LookupError, match="another library"):
        photos_app.cmd_add_to_album(Namespace(name="Dogs", uuids=[lib["dog0"]]))
    with pytest.raises(LookupError, match="another library"):
        cli.cmd_album(Namespace(name="Dogs", query="dog", k=5, person=None, after=None, before=None, place=None, kind=None))
    assert fake.albums == {}


def test_claudes_make_album_goes_through_the_check(lib, monkeypatch):
    from photosearch import mcp_server
    fake = FakePhotos(monkeypatch, indexed={lib["dog0"], lib["dog1"]}, open_has={lib["dog0"], lib["dog1"]})
    assert mcp_server.make_album("Dogs", [lib["dog0"], lib["dog1"]]) == "added 2 of 2 photos to album 'Dogs'"
    fake.albums.clear()
    FakePhotos(monkeypatch, indexed={lib["dog0"]}, open_has=set())
    with pytest.raises(LookupError):
        mcp_server.make_album("Dogs", [lib["dog0"]])
