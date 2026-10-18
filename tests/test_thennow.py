"""Then and now: two photos from the same spot, years apart, that look alike."""
import json
import numpy as np
import pytest

from photosearch import store, thennow
from library import axis, noise, unit
from server import Server

SPOT = (48.5000, -123.4000)  # far from the made-up library's own places


@pytest.fixture
def spot(con):
    """A lookout shot over the years: a view, nudged a little each time, at a spot or a few metres off."""
    rng = np.random.default_rng(5)
    view = unit(axis("beach") + noise(rng, 0.3))
    n = 0
    def add(when, vec=None, metres=0):
        nonlocal n
        n += 1
        u = f"VIEW-{n:03}"
        v = unit(view + noise(rng, 0.25)) if vec is None else vec
        con.execute("insert into photos (uuid, date, kind, title, place, persons, albums, labels, src, vec, lat, lon, geo) "
                    "values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (u, when + "T10:00:00-08:00", "photo", "", "Mount Doug", "[]", "[]",
                    "[]", "", v.tobytes(), SPOT[0] + metres / 111_000, SPOT[1], "{}"))
        return u
    out = dict(then=add("2017-08-06"), now=add("2023-08-04", metres=40),
               again=add("2017-08-08"), again_now=add("2023-08-05"),  # the same two outings: one pair is enough
               far=add("2024-07-01", metres=2000),
               other=add("2025-01-01", vec=unit(axis("dog") + noise(rng, 0.3))))
    copy = unit(view + noise(rng, 0.02))
    out["copy_then"], out["copy_now"] = add("2016-05-01", vec=copy), add("2022-05-01", vec=copy)  # one photo, saved twice
    con.commit(); store._vecs = (None,) + store._vecs[1:]; thennow._pairs = (None, None)
    return out


def found(con, spot):
    mine = set(spot.values())
    return [(a, b) for _, a, b in thennow.pairs(con) if a in mine or b in mine]


def test_the_same_spot_years_apart_is_a_pair(con, spot):
    got = found(con, spot)
    assert (spot["then"], spot["now"]) in got or (spot["again"], spot["again_now"]) in got
    for a, b in got:  # then comes first, and 4 years or more before
        da, db = (con.execute("select date from photos where uuid=?", (u,)).fetchone()[0] for u in (a, b))
        assert int(db[:4]) - int(da[:4]) >= thennow.YEARS


def test_copies_far_photos_and_repeat_outings_are_left_out(con, spot):
    got = found(con, spot)
    used = {u for p in got for u in p}
    assert spot["far"] not in used and spot["other"] not in used
    assert (spot["copy_then"], spot["copy_now"]) not in got
    outings = [p for p in got if {spot["then"], spot["again"]} & set(p[:1]) and {spot["now"], spot["again_now"]} & set(p[1:])]
    assert len(outings) == 1


def test_the_page_lists_pairs(con, spot):
    srv = Server()
    try:
        r = srv.json("/api/thennow")
        mine = [x for x in r if x["then"]["uuid"].startswith("VIEW-")]
        assert mine and mine[0]["years"] >= 4 and mine[0]["now"]["place"] == "Mount Doug"
        assert json.dumps(mine)  # plain JSON for the page
    finally:
        srv.close()


@pytest.fixture
def family(con):
    """Sam on the couch over the years, no GPS: alone, with one more named, and in a crowd of four named people."""
    rng = np.random.default_rng(9)
    couch = unit(axis("face") + noise(rng, 0.3))
    n = 0
    def add(when, persons, vec=None):
        nonlocal n
        n += 1
        u = f"COUCH-{n:03}"
        v = unit(couch + noise(rng, 0.2)) if vec is None else vec
        con.execute("insert into photos (uuid, date, kind, title, place, persons, albums, labels, src, vec, geo) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)", (u, when + "T10:00:00-08:00", "photo", "", "", json.dumps(persons),
                    "[]", "[]", "", v.tobytes(), "{}"))
        return u
    out = dict(baby=add("2009-06-01", ["Sam Lee"]), boy=add("2015-06-01", ["Sam Lee", "Ana Lee"]),
               crowd=add("2010-01-01", ["Sam Lee", "Ana Lee", "Ben Lee", "Cy Lee"]), crowd_now=add("2018-01-01", ["Sam Lee"]),
               stranger=add("2020-06-01", ["Dee Roe"]))
    con.commit(); store._vecs = (None,) + store._vecs[1:]; thennow._people = (None, None)
    return out


def test_the_same_person_years_apart_is_a_pair(con, family):
    got = {(a, b): n for _, n, a, b in thennow.person_pairs(con) if a.startswith("COUCH-")}
    assert [n for (a, b), n in got.items() if a == family["baby"]] == ["Sam Lee"]  # with a later Sam, 6 or 9 years on
    assert all(family["crowd"] not in p and family["stranger"] not in p for p in got)  # a crowd; someone else


def test_the_page_lists_pairs_of_a_person(con, family):
    srv = Server()
    try:
        r = [x for x in srv.json("/api/thennow?by=person") if x["then"]["uuid"].startswith("COUCH-")]
        assert r and r[0]["who"] == "Sam Lee" and r[0]["years"] >= 4
        assert all("who" not in x for x in srv.json("/api/thennow"))
    finally:
        srv.close()
