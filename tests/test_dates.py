"""The date detective: photos on a placeholder date get dated a group at a time, in this index and never in Photos."""
import json
from urllib.parse import urlencode
import numpy as np
import pytest

from photosearch import dates, explore, store
from library import axis, noise, unit
from server import Server

PLACEHOLDER = "2002-01-01T00:00:00-08:00"


@pytest.fixture
def undated(con, lib):
    """65 scans that Photos dates 2002-01-01, as on the real library: a beach album named with its month, two albums
    named by weeks, two loose shots of snow, and a "Roll 1" holding most of them."""
    rng = np.random.default_rng(3)
    n = 0
    def add(concept, albums, persons=()):
        nonlocal n
        n += 1
        u = f"SCAN-{n:03}"
        vec = unit(0.6 * axis("fun") + axis(concept) + noise(rng, 0.2))
        con.execute("insert into photos (uuid, date, kind, title, place, persons, albums, labels, src, vec, geo) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)", (u, PLACEHOLDER, "photo", f"P10100{n % 100:02}.JPG", "",
                    json.dumps(list(persons)), json.dumps(albums), "[]", "", vec.tobytes(), "{}"))
        return u
    out = dict(coast=[add("beach", ["Coast July 2019", "Roll 1"]) for _ in range(30)],
               early=[add("face", ["Baby weeks 2-3"], ["Sam"]) for _ in range(20)],
               later=[add("face", ["Baby weeks 6-7", "Roll 1"], ["Sam"]) for _ in range(10)],
               loose=[add("snow", ["Roll 1"]) for _ in range(2)],
               printed=[add("dog", ["Roll 1", "for print"]) for _ in range(3)])
    con.execute("update photos set albums='[\"for print\"]' where uuid=?", (lib["dog0"],))  # it mixes years
    con.commit(); store._vecs = (None,) + store._vecs[1:]
    return out


def group(con, album):
    return next(g for g in dates.groups(con) if g["album"] == album)


def test_photos_are_grouped_by_their_own_album(con, undated):
    gs = dates.groups(con)
    by = {g["album"] or g["id"]: g["uuids"] for g in gs}
    assert set(by["Coast July 2019"]) == set(undated["coast"]) and set(by["Baby weeks 6-7"]) == set(undated["later"])
    assert "Roll 1" not in by and "for print" not in by  # it spans the others; it holds a dated photo
    loose = [g["uuids"] for g in gs if not g["album"]]
    assert sorted(sum(loose, [])) == sorted(undated["loose"] + undated["printed"])
    assert sorted(undated["loose"]) in [sorted(g) for g in loose]  # the two snow shots together
    assert sum(map(len, by.values())) == 65


def test_an_album_named_with_a_month_is_the_guess(con, undated):
    c = dates.clues(con, group(con, "Coast July 2019"))
    assert c["guess"] == dict(year=2019, month=7, how="the album name")
    assert c["alike"] and all(x["date"] < "2030" for x in c["alike"])


def test_dating_one_album_dates_its_series(con, undated):
    first = dates.clues(con, group(con, "Baby weeks 6-7"))
    assert first["guess"]["how"] == "look-alikes" and any("Sam is in dated photos from 2018" in c for c in first["clues"])
    dates.set_date(con, undated["early"], 2020, 3)
    c = dates.clues(con, group(con, "Baby weeks 6-7"))
    assert c["guess"] == dict(year=2020, month=4, how="“Baby weeks 2-3”, already dated")  # 4 weeks after March 15


def test_a_dated_group_joins_the_dated_photos(con, undated):
    coast = undated["coast"]
    assert all(x.get("undated") for x in store.photo_info(con, coast).values())
    assert dates.set_date(con, coast, 2019, 7) == 30
    info = store.photo_info(con, coast)
    assert {x["date"] for x in info.values()} == {"2019-07-15"} and {x["approx"] for x in info.values()} == {"month"}
    times = [d for (d,) in con.execute("select date from photos where uuid like 'SCAN-%' and date like '2019%' order by title")]
    assert times[0] == "2019-07-15T12:00:00-08:00" and times[1] == "2019-07-15T12:01:00-08:00"  # in file-name order
    # 35 photos are left on the placeholder: fewer than 50 share it now, and it's still not a date
    assert all(x.get("undated") for x in store.photo_info(con, undated["early"]).values())
    assert len(dates.placeholder(con)) == 35 and len(dates.groups(con)) == 4
    assert 2019 in {int(x) for (x,) in con.execute(f"select substr(date,1,4) from photos where uuid like 'SCAN-%' and {store.DATED}")}


def test_dates_survive_a_refresh_from_photos_and_can_be_undone(con, undated):
    dates.set_date(con, undated["coast"], 2019, 7, 20)
    con.execute("update photos set date=? where uuid like 'SCAN-%'", (PLACEHOLDER,)); con.commit()  # what index does
    dates.apply(con)
    assert store.photo_info(con, undated["coast"][:1])[undated["coast"][0]]["date"] == "2019-07-20"
    assert dates.undo(con, undated["coast"][:5]) == 5 and dates.undo(con) == 25
    assert len(dates.placeholder(con)) == 65


def test_on_this_day_leaves_out_a_guessed_month(con, undated):
    dates.set_date(con, undated["coast"][:15], 2019, 7)
    dates.set_date(con, undated["coast"][15:], 2019, 7, 15)
    shown = {p["uuid"] for y in explore.on_this_day(con, "07-15")["years"] for p in y["photos"]}
    assert shown & set(undated["coast"][15:]) and not shown & set(undated["coast"][:15])


def test_names_and_dates_are_read():
    assert dates.name_date("Bhutan January 2007") == (2007, 1) and dates.name_date("Summer 2004") == (2004, None)
    assert dates.name_date("Roll 1") is None and dates.name_date("Bangkok Feb 2006") == (2006, 2)
    assert dates.series("Arshan weeks 12-14") == ("arshan", 91) and dates.series("Arshan first eid days 1-2") is None
    assert dates.parse_when("2007-01") == (2007, 1, None)
    with pytest.raises(SystemExit):
        dates.parse_when("2007-13")


def test_the_page_dates_a_group(con, undated):
    srv = Server()
    try:
        r = srv.json("/api/undated")
        assert r["left"] == 65 and r["group"]["album"] == "Coast July 2019" and r["group"]["guess"]["month"] == 7
        uuids = [x["uuid"] for x in r["group"]["photos"]][1:]  # one left out
        assert srv.json("/api/undated", dict(uuids=uuids, year=2019, month=7)) == 29
        r = srv.json("/api/undated?" + urlencode(dict(skip=r["group"]["id"] + "|a:Baby, weeks")))
        assert r["left"] == 36 and r["group"]["album"] != "Coast July 2019"
        assert srv.json("/api/undated_undo", dict(uuids=uuids)) == 29
    finally:
        srv.close()
