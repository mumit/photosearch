import json

import pytest

from photosearch import explore, people, places, search, store, stories


def names(lib, results):
    inv = {v: k for k, v in lib.items()}
    return [inv.get(r["uuid"] if isinstance(r, dict) else r, "?") for r in results]


def test_search_finds_what_the_words_describe(lib, con):
    top = names(lib, search.search(con, "dog playing", 9))
    assert sorted(top) == sorted([f"dog{i}" for i in range(8)] + ["video"])  # the video is of the dog too


def test_exclude_pushes_matches_away(lib, con):
    both = names(lib, search.search(con, "beach dog", 10))
    without = names(lib, search.search(con, "beach dog", 10, exclude="dog"))
    assert any(n.startswith("dog") for n in both[:10])
    assert not any(n.startswith("dog") for n in without[:8])


def test_scores_come_best_first(con):
    scores = [r["score"] for r in search.search(con, "snow", 20)]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("filters, check", [
    (dict(person="sam"), lambda p: "Sam" in p["persons"]),                        # substring, any case
    (dict(person=["Sam", "Alex"]), lambda p: {"Sam", "Alex"} <= set(p["persons"])),  # all of them
    (dict(place="lisbon"), lambda p: "Lisbon" in p["place"]),
    (dict(after="2025-01-01", before="2025-06-01"), lambda p: "2025-01-01" <= p["date"] < "2025-06-01"),
    (dict(kind="video"), lambda p: p["kind"] == "video"),
    (dict(months=search.SEASONS["winter"]), lambda p: int(p["date"][5:7]) in (12, 1, 2)),
])
def test_filters(con, filters, check):
    res = search.search(con, "a photo", 100, **filters)
    assert res and all(check(p) for p in res)


def test_similar_finds_its_own_kind_but_not_itself(lib, con):
    res = names(lib, search.similar(con, lib["cake0"], 4))
    assert sorted(res) == ["cake1", "cake2", "cake3", "cake4"]


def test_similar_to_an_unknown_photo(con):
    with pytest.raises(LookupError):
        search.similar(con, "00000000-0000-0000-0000-000000000000")


def test_documents_are_boring(lib, con):
    _, _, pos = store.vectors(con)
    s = search.interest(con)
    assert s[pos[lib["receipt0"]]] < 0 < s[pos[lib["beach0"]]]


def test_filters_only_gives_their_most_interesting(lib, con):
    res = search.best_of(con, 50, person=["Sam"])
    assert res and all("Sam" in p["persons"] for p in res)
    assert [p["score"] for p in res] == sorted((p["score"] for p in res), reverse=True)


def test_photo_info_carries_shape(lib, con):
    info = store.photo_info(con, [lib["screen0"], lib["beach0"]])
    assert info[lib["screen0"]]["ar"] == pytest.approx(184 / 400, abs=0.01)
    assert info[lib["beach0"]]["ar"] == pytest.approx(4 / 3, abs=0.01)


def test_timeline_one_per_year(con):
    years = [y["year"] for y in explore.timeline(con, "birthday cake")]
    assert years == sorted(set(years))
    assert all(len(y["results"]) == 1 for y in explore.timeline(con, "birthday cake"))


def test_timeline_for_a_person(con):
    for y in explore.timeline(con, "", 2, person="Alex"):
        assert all("Alex" in p["persons"] for p in y["results"])


def test_photo_math_leaves_out_the_base(lib, con):
    res = explore.photo_math(con, lib["dog0"], plus="snow", minus="dog", k=5)
    assert lib["dog0"] not in {r["uuid"] for r in res}
    assert names(lib, res)[0].startswith(("snow", "alike"))


def test_overview(con):
    o = explore.overview(con)
    assert dict(o["people"])["Sam"] > 0 and dict(o["places"])["Lisbon"] == 22


def test_people_and_person(lib, con):
    who = {p["name"]: p for p in people.people(con)}
    assert set(who) == {"Sam", "Alex"}
    assert who["Sam"]["cover"] == lib["portrait"]  # the close-up of Sam alone
    sam = people.person(con, "Sam")
    assert sam["portrait"] == lib["portrait"] and dict(sam["together"])["Alex"] > 0
    with pytest.raises(LookupError):
        people.person(con, "Nobody")


def test_trips_find_the_week_away(con):
    t = places.trips(con)
    assert [(x["id"], x["name"], x["photos"]) for x in t] == [("trip-2025-03-10", "Lisbon", 22)]


def test_world_regions(con):
    w = places.world(con)
    assert {r["name"] for r in w["regions"]} >= {"Portland", "Lisbon", "Cannon Beach"}
    assert sum(c["n"] for c in w["cells"]) == con.execute("select count(*) from photos where lat is not null").fetchone()[0]


def test_near(lib, con):
    r = places.near(con, 38.72, -9.14, radius_km=5)
    assert r["n"] == 22 and all(p["place"].startswith("Lisbon") for p in r["photos"])


def test_days_calendar(lib, con):
    d = explore.days(con, 2025)
    assert d["year"] == 2025 and {x["d"] for x in d["days"]} >= {"2025-03-10", "2025-03-14"}
    assert sum(x["n"] for x in d["days"] if x["d"].startswith("2025-03")) == 22


def test_on_this_day(con):
    r = explore.on_this_day(con, "03-12")
    assert r["years"][0]["year"] == 2025 and r["years"][0]["trip"]["name"] == "Lisbon"
    with pytest.raises(LookupError):
        explore.on_this_day(con, "13-45")


def test_highlights_skip_documents(lib, con):
    picked = {p["uuid"] for p in stories.highlights(con, "2023-01-01", "2024-12-31", 60)}
    assert picked and not picked & {lib["receipt0"], lib["receipt1"], lib["receiptcopy0"], lib["receiptcopy1"]}


def test_game_round(con):
    for mode in ("year", "place"):
        g = explore.game_round(con, mode)
        assert g["first"] <= int(g["date"][:4]) <= g["last"]
        if mode == "place":
            assert g["lat"] is not None


def test_dated_leaves_out_shared_timestamps(con):
    # 50+ photos sharing one timestamp are scans or a reset camera clock, not real dates
    rows = [(f"FA{n:06X}-0000-0000-0000-000000000000", "2002-01-01T00:00:00", "photo", "", "", "[]", "[]", "[]", "",
             con.execute("select vec from photos limit 1").fetchone()[0], None, None, "{}") for n in range(50)]
    con.executemany("insert into photos (uuid, date, kind, title, place, persons, albums, labels, src, vec, lat, lon, geo) "
                    "values(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows); con.commit()
    assert 2002 not in {y["year"] for y in explore.timeline(con, "a photo")}
    assert store.photo_info(con, [rows[0][0]])[rows[0][0]]["undated"] is True
    assert json.loads(json.dumps(stories.stories(con)))  # still renders
