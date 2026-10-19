"""Family picks: anyone loves a photo under their own name; the most loved come first."""
import pytest

from photosearch import picks


def test_loving_and_unloving(con, lib):
    assert picks.pick(con, lib["dog0"], "Sam") == ["Sam"]
    assert picks.pick(con, lib["dog0"], " Sam ") == ["Sam"]  # once each, however it's typed
    assert picks.pick(con, lib["dog0"], "Mum") == ["Sam", "Mum"]
    assert picks.pick(con, lib["dog0"], "Sam", on=False) == ["Mum"]
    assert picks.loved_by(con, lib["beach0"]) == []


def test_most_loved_first_then_newest(con, lib):
    picks.pick(con, lib["beach0"], "Sam"); picks.pick(con, lib["dog0"], "Sam"); picks.pick(con, lib["dog0"], "Mum")
    picks.pick(con, lib["cake0"], "Mum")
    r = picks.picks(con)
    assert [p["uuid"] for p in r["photos"]] == [lib["dog0"], lib["cake0"], lib["beach0"]]
    assert r["photos"][0]["by"] == ["Sam", "Mum"] and r["photos"][0]["date"]
    assert r["people"] == [dict(who="Mum", n=2), dict(who="Sam", n=2)]
    assert [p["uuid"] for p in picks.picks(con, "Sam")["photos"]] == [lib["dog0"], lib["beach0"]]


def test_a_photo_gone_from_the_index_drops_out(con, lib):
    picks.pick(con, lib["dog0"], "Sam")
    con.execute("delete from photos where uuid=?", (lib["dog0"],))
    assert picks.picks(con)["photos"] == []


@pytest.mark.parametrize("who", ["", "   ", None])
def test_someone_must_be_picking(con, lib, who):
    with pytest.raises(ValueError):
        picks.pick(con, lib["dog0"], who)


def test_only_indexed_photos(con):
    with pytest.raises(LookupError):
        picks.pick(con, "nope", "Sam")


def test_the_page_picks(lib):
    from server import Server
    srv = Server()
    try:
        _the_page_picks(srv, lib)
    finally:
        srv.close()


def _the_page_picks(srv, lib):
    assert srv.json("/api/pick", dict(uuid=lib["dog0"], who="Sam")) == ["Sam"]
    assert srv.json(f"/api/loved?uuid={lib['dog0']}") == ["Sam"]
    assert srv.json("/api/picks")["photos"][0]["by"] == ["Sam"]
    assert srv.post("/api/pick", dict(uuid=lib["dog0"]))[0] == 400  # nobody
    srv.json("/api/pick", dict(uuid=lib["dog0"], who="Sam", on=False))
