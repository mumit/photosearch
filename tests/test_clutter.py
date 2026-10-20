"""Tidying up clutter: screenshots, IDs and cards, receipts and papers, accidental shots, each to its own album in
Photos (the stand-in), only by adding."""
import json
from datetime import datetime
from types import SimpleNamespace

from photosearch import clutter, index, store
from server import Server


def test_receipts_and_screenshots_are_found_and_nothing_else(con, lib):
    f = clutter.found(con)
    assert set(f["papers"]) == {lib[n] for n in ("receipt0", "receipt1", "receiptcopy0", "receiptcopy1")}
    assert set(f["screenshots"]) == {lib["screen0"], lib["screen1"]}  # by their phone-screen shape
    every = [u for us in f.values() for u in us]
    assert len(every) == len(set(every))  # one kind each
    assert not {lib[n] for n in ("beach0", "dog0", "portrait", "video")} & set(every)


def test_photos_own_screenshot_mark_wins_over_the_shape(con, lib):
    con.execute("update photos set flags='[]'")
    con.execute("update photos set flags='[\"screenshot\"]' where uuid=?", (lib["dog3"],)); con.commit()
    clutter._found = (None, None)
    assert clutter.found(con)["screenshots"] == [lib["dog3"]]


def test_index_keeps_what_photos_marks():
    p = SimpleNamespace(date=datetime(2024, 1, 1), ismovie=False, title="", place=None, persons=[], albums=[], labels=[],
                        location=(None, None), screenshot=True, selfie=False)
    cols = index.META_COLS.split(", ")
    assert json.loads(index.meta(p)[cols.index("flags")]) == ["screenshot"]


def test_not_clutter_stops_a_suggestion(con, lib):
    r = clutter.clutter(con, "papers")
    assert r["total"] == 4 and {k["kind"]: k["n"] for k in r["kinds"]}["papers"] == 4
    clutter.clutter_choose(con, dict(action="not", uuid=lib["receipt0"]))
    assert lib["receipt0"] not in {p["uuid"] for p in clutter.clutter(con, "papers")["photos"]}
    clutter.clutter_choose(con, dict(action="is", uuid=lib["receipt0"]))
    assert clutter.clutter(con, "papers")["total"] == 4


def test_a_kind_goes_to_its_own_album_once(con, lib, photos_app):
    clutter.clutter_choose(con, dict(action="not", uuid=lib["receipt1"]))
    assert clutter.clutter_send(con, "papers") == dict(added=3, album="Photosearch · receipts and papers")
    (album, sent), = photos_app.added
    assert album == "Photosearch · receipts and papers"
    assert set(sent) == {lib[n] for n in ("receipt0", "receiptcopy0", "receiptcopy1")}  # not the one taken out
    assert clutter.clutter_send(con, "papers")["added"] == 0  # already there
    r = clutter.clutter(con, "papers")
    assert {k["kind"]: k["sent"] for k in r["kinds"]}["papers"] == 3 and all(p["sent"] for p in r["photos"])


def test_the_page_lists_and_sends(lib, photos_app):
    srv = Server()
    try:
        kinds = {k["kind"]: k for k in srv.json("/api/clutter")["kinds"]}
        assert list(kinds) == ["ids", "screenshots", "papers", "accidents"] and kinds["screenshots"]["n"] == 2
        assert srv.json("/api/clutter?kind=screenshots")["total"] == 2
        assert srv.json("/api/clutter_send", dict(kind="screenshots"))["added"] == 2
        assert srv.post("/api/clutter_send", dict(kind="nope"))[0] == 400
    finally:
        srv.close()
