"""Recreate this: old photos worth shooting again, picked, and matched to the new shot once it's in the library."""
import json
from datetime import date

import numpy as np
import pytest

from photosearch import recreate, store
from library import axis, noise, unit
from server import Server


@pytest.fixture
def sam(con, monkeypatch):
    """Sam over the years: posed with a cake (the fake model's "pose"), in a crowd, on another day; Ana this year."""
    monkeypatch.setattr(recreate, "POSE", ["a birthday cake"])
    rng = np.random.default_rng(4)
    posed = unit(axis("cake") + noise(rng, 0.3))
    n = 0
    def add(when, persons, vec=None):
        nonlocal n
        n += 1
        u = f"SAM-{n:03}"
        v = unit(posed + noise(rng, 0.2)) if vec is None else vec
        con.execute("insert into photos (uuid, date, kind, title, place, persons, albums, labels, src, vec, geo) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)", (u, when + "T10:00:00-08:00", "photo", "", "", json.dumps(persons),
                    "[]", "[]", "", v.tobytes(), "{}"))
        return u
    out = dict(cake=add("2012-05-01", ["Sam Lee"]), same_day=add("2012-05-01", ["Sam Lee"]),
               crowd=add("2011-05-01", ["Sam Lee", "Ana Lee", "Ben Lee"]),
               recent=add(f"{date.today().year}-01-02", ["Sam Lee"]))
    con.commit(); store._vecs = (None,) + store._vecs[1:]; recreate._ideas = (None, None)
    return out, add


def mine(xs):
    return [x["uuid"] for x in xs if x["uuid"].startswith("SAM-")]


def test_ideas_are_old_posed_photos_one_a_day(con, sam):
    sam, _ = sam
    got = mine(recreate.ideas(con, limit=60))
    assert len({sam["cake"], sam["same_day"]} & set(got)) == 1  # one a day
    assert sam["crowd"] not in got and sam["recent"] not in got  # too many people; too new
    first = recreate.ideas(con, limit=60)[0]
    assert first["uuid"].startswith("SAM-") and first["who"] == "Sam Lee"


def test_a_new_shot_is_offered_and_confirmed(con, sam):
    sam, add = sam
    old = mine(recreate.ideas(con, limit=60))[0]
    recreate.pick(con, old)
    assert old not in mine(recreate.ideas(con, limit=60))
    r = recreate.recreations(con)
    assert [x["then"]["uuid"] for x in r["todo"]] == [old] and "shot" not in r["todo"][0]  # older photos aren't new shots
    today = date.today().isoformat()
    wrong = add(today, ["Sam Lee"])
    store._vecs = (None,) + store._vecs[1:]
    assert recreate.recreations(con)["todo"][0]["shot"]["uuid"] == wrong
    recreate.answer(con, old, wrong, yes=False)
    right = add(today, [])  # Photos hasn't named the face yet
    store._vecs = (None,) + store._vecs[1:]
    assert recreate.recreations(con)["todo"][0]["shot"]["uuid"] == right
    recreate.answer(con, old, right, yes=True)
    done = recreate.recreations(con)["done"]
    assert done[0]["then"]["uuid"] == old and done[0]["now"]["uuid"] == right and done[0]["years"] >= recreate.AGE


def test_the_page_picks_and_unpicks(con, sam):
    srv = Server()
    try:
        ideas = mine(srv.json("/api/recreate?view=ideas&limit=60"))
        r = srv.json("/api/recreate", dict(uuid=ideas[0], action="pick"))
        assert [x["then"]["uuid"] for x in r["todo"]] == [ideas[0]]
        r = srv.json("/api/recreate", dict(uuid=ideas[0], action="unpick"))
        assert r == dict(todo=[], done=[])
        assert srv.post("/api/recreate", dict(uuid=ideas[0], action="explode"))[0] == 400
    finally:
        srv.close()
