"""`serve --demo`: presenter mode only runs on a demo's own index, and shows nothing about this Mac."""
import json
from argparse import Namespace

import pytest

from photosearch import config, server
from server import Server

DEMO = "/Users/x/Pictures/Photosearch Demo.photoslibrary"


def record_library(con, path):
    con.execute("insert or replace into meta values('library', ?)", (path,)); con.commit()


def args(**kw):
    return Namespace(**dict(dict(port=8765, lan=False, new_passcode=False, demo=True), **kw))


def test_a_demo_index_is_fine(con):
    record_library(con, DEMO)
    assert server.presenter_library(args()) == "Photosearch Demo"


def test_not_with_lan(con):
    record_library(con, DEMO)
    with pytest.raises(SystemExit, match="--lan"):
        server.presenter_library(args(lan=True))


def test_not_on_the_default_data_folder(con, monkeypatch):
    record_library(con, DEMO)
    monkeypatch.setattr(server, "DATA", config.ROOT / "data")
    with pytest.raises(SystemExit, match="your own library"):
        server.presenter_library(args())


def test_not_on_an_index_that_doesnt_say_which_library(con):
    with pytest.raises(SystemExit, match="doesn't record"):
        server.presenter_library(args())


def test_not_on_an_index_of_the_system_library(con):
    record_library(con, str(config.LIBRARY))
    with pytest.raises(SystemExit, match="your own library"):
        server.presenter_library(args())


def test_the_page_hides_this_macs_details(con, monkeypatch):
    record_library(con, DEMO)
    s = Server(monkeypatch, demo=True)
    try:
        status, _, body = s.get("/")
        page = json.loads(body.decode().split("const SERVER = ", 1)[1].split(";</script>", 1)[0])
        assert page["demo"] is True and not page["lan"]
        assert s.get("/api/open?uuid=x")[0] == 403  # it would open Photos on this screen
        assert s.get("/api/search?q=beach")[0] == 200
    finally:
        s.close()
