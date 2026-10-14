import json

import numpy as np
import pytest

from photosearch import albums, config
from library import axis, unit


def test_create_keeps_the_chosen_size(con):
    a = albums.save_album(con, dict(name="Beach days", q="beach", n=5))
    assert a == dict(id="beach-days", n=5)
    assert len(albums.album_view(con, "beach-days")["photos"]) == 5


def test_a_new_album_never_overwrites_one_with_the_same_name(con):
    albums.save_album(con, dict(name="Beach", q="beach", n=3))
    again = albums.save_album(con, dict(name="Beach", q="snow", n=3))
    assert again["id"] == "beach-2"
    assert albums.load_album("beach")["q"] == "beach"


def test_without_a_size_it_takes_the_close_matches(lib, con):
    albums.save_album(con, dict(name="Beach", q="beach"))
    members = set(albums.album_members(con, albums.load_album("beach")))
    beaches = {lib[f"beach{i}"] for i in range(8)} | {lib["copy0"], lib["copy1"]}
    assert members == beaches  # all ten beach photos, and none of the rest


def test_taking_one_out_teaches_but_keeps_the_size(lib, con):
    albums.save_album(con, dict(name="Beach", q="beach", n=6))
    first = albums.album_members(con, albums.load_album("beach"))
    out = first[0]
    albums.save_album(con, dict(id="beach", name="Beach", q="beach", n=6, removed=[out]))
    after = albums.album_members(con, albums.load_album("beach"))
    assert len(after) == 6 and out not in after


def test_pinned_photos_stay_in(lib, con):
    albums.save_album(con, dict(name="Beach", q="beach", n=3, pinned=[lib["dog3"]]))
    assert lib["dog3"] in albums.album_members(con, albums.load_album("beach"))
    assert next(p for p in albums.album_preview(con, albums.load_album("beach"))["ranked"] if p["uuid"] == lib["dog3"])["pinned"]


def test_new_photos_that_match_join_by_themselves(con):
    albums.save_album(con, dict(name="Beach", q="beach", n=10))
    v = unit(0.6 * axis("fun") + axis("beach"))  # a perfect beach photo, indexed after the album was made
    con.execute("insert into photos(uuid, date, kind, place, persons, albums, labels, src, vec) values(?,?,?,?,?,?,?,?,?)",
                ("ABCDEF01-0000-0000-0000-000000000001", "2026-07-01T12:00:00", "photo", "", "[]", "[]", "[]", "", v.tobytes()))
    con.commit()
    assert "ABCDEF01-0000-0000-0000-000000000001" in albums.album_members(con, albums.load_album("beach"))


def test_an_album_of_filters_holds_everything_that_passes(lib, con):
    albums.save_album(con, dict(name="Sam", filters=dict(person="Sam")))
    members = albums.album_members(con, albums.load_album("sam"))
    tagged = [u for u, p in con.execute("select uuid, persons from photos") if "Sam" in json.loads(p)]
    assert sorted(members) == sorted(tagged)
    albums.save_album(con, dict(id="sam", name="Sam", filters=dict(person="Sam"), removed=[members[0]]))
    assert members[0] not in albums.album_members(con, albums.load_album("sam"))


def test_filters_narrow_a_search_album(con):
    albums.save_album(con, dict(name="City", q="city", filters=dict(place="Lisbon", season="spring"), n=40))
    photos = albums.album_view(con, "city")["photos"]
    assert photos and all(p["place"].startswith("Lisbon") and p["date"][5:7] in ("03", "04", "05") for p in photos)


def test_albums_list(con):
    albums.save_album(con, dict(name="Dog", q="dog", n=4))
    [a] = albums.albums(con)
    assert (a["id"], a["n"], a["new"]) == ("dog", 4, None)
    assert a["cover"] in albums.album_members(con, albums.load_album("dog"))


def test_identical_copies_go_in_together(lib, con):
    # copy0 and copy1 are the same picture, so the same score: an album ending at one takes both
    ranked = [u for u, _ in albums.album_rank(con, dict(q="beach"))]
    n = min(ranked.index(lib["copy0"]), ranked.index(lib["copy1"])) + 1
    albums.save_album(con, dict(name="Beach", q="beach", n=n))
    assert {lib["copy0"], lib["copy1"]} <= set(albums.album_members(con, albums.load_album("beach")))


@pytest.mark.parametrize("body, msg", [
    ({}, "needs a name"),
    (dict(name="   "), "needs a name"),
    (dict(name="Nothing"), "words or a filter"),
    ("not a dict", "expected an album"),
])
def test_bad_albums_are_refused(con, body, msg):
    with pytest.raises(ValueError, match=msg):
        albums.save_album(con, body)


def test_junk_photo_ids_are_dropped(lib, con):
    albums.save_album(con, dict(name="Beach", q="beach", n=3, pinned=["../../etc/passwd", "<script>", lib["dog1"]], removed=[{"x": 1}]))
    a = albums.load_album("beach")
    assert a["pinned"] == [lib["dog1"]] and a["removed"] == []


def test_long_fields_are_cut(con):
    albums.save_album(con, dict(name="N" * 500, q="beach " * 200, n=3))
    a = albums.albums(con)[0]
    assert len(a["name"]) == 80 and len(a["q"]) <= 300


@pytest.mark.parametrize("aid", ["../index", "..", "a/b", "UPPER", "", "x" * 61, "beach.json"])
def test_album_ids_cant_reach_other_files(con, aid):
    with pytest.raises(LookupError):
        albums.load_album(aid)
    with pytest.raises(LookupError):
        albums.delete_album(aid)
    assert config.DB.exists()


def test_delete(con):
    albums.save_album(con, dict(name="Beach", q="beach", n=3))
    albums.delete_album("beach")
    assert albums.albums(con) == []
    with pytest.raises(LookupError):
        albums.album_view(con, "beach")


def test_copy_to_photos_adds_only_whats_new(con, photos_app):
    albums.save_album(con, dict(name="Dog", q="dog", n=4))
    assert albums.album_to_photos(con, "dog") == dict(added=4, total=4)
    assert albums.albums(con)[0]["new"] == 0
    albums.save_album(con, dict(id="dog", name="Dog", q="dog", n=6))
    assert albums.albums(con)[0]["new"] == 2
    assert albums.album_to_photos(con, "dog")["added"] == 2
    assert [(name, len(u)) for name, u in photos_app.added] == [("Dog", 4), ("Dog", 2)]


def test_album_vector_is_unit_length(lib, con):
    a = dict(q="beach", pinned=[lib["dog0"]], removed=[lib["beach0"]])
    assert np.linalg.norm(albums.album_vector(con, a)) == pytest.approx(1, abs=1e-5)
    assert albums.album_vector(con, dict(filters=dict(person="Sam"))) is None


@pytest.mark.parametrize("aid", ["../x", "../../reviews/2024", "nope", "Beach"])
def test_updates_only_touch_albums_that_exist(con, aid):
    with pytest.raises(LookupError):
        albums.save_album(con, dict(id=aid, name="x", q="beach"))
    assert not (config.DATA / "x.json").exists() and not albums.ALBUMS.exists()
