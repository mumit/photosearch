"""`photosearch demo-check` catches a demo that gives away your own library."""
import shutil, sqlite3
from argparse import Namespace

import pytest

from photosearch import config, demo


def test_a_demo_made_of_your_own_library_fails_on_everything(con, tmp_path, capsys):
    real = tmp_path / "real"; real.mkdir()
    shutil.copy(config.DB, real / "index.sqlite")  # "your library" is the same photos, names and places
    con.execute("insert into meta values('library', '/Users/x/Pictures/Photosearch Demo.photoslibrary')"); con.commit()
    with pytest.raises(SystemExit, match="problem"):
        demo.cmd_demo_check(Namespace(real=str(real)))
    out = capsys.readouterr().out
    assert "is from your own library" in out and "has people tagged" in out and "a location near your home" in out
    assert "shows 'Sam' (a name in your library)" in out and "'Portland'" in out


def test_refuses_to_compare_the_demo_with_itself(con):
    with pytest.raises(SystemExit, match="own library's data folder"):
        demo.cmd_demo_check(Namespace(real=str(config.DATA)))


def test_your_library_lists_names_and_home_places_but_not_countries(tmp_path):
    names, places, ids, home = demo.your_library(config.DATA)
    assert {"Sam", "Alex"} <= names and "Portland" in places and "USA" not in places and "Oregon" not in places
    assert "Lisbon" not in places and len(ids) == 73


def test_photos_looked_at_by_eye_dont_fail(con, monkeypatch, tmp_path, capsys):
    real = tmp_path / "real"; real.mkdir()
    con.execute("insert into meta values('library', '/Users/x/Pictures/Photosearch Demo.photoslibrary')"); con.commit()
    sqlite3.connect(real / "index.sqlite").executescript(
        "create table photos(uuid text, date text, persons text, place text, lat real, lon real, geo text);")
    con.execute("update photos set persons='[]', lat=null, lon=null, place=''"); con.commit()
    first = con.execute("select uuid from photos").fetchone()[0]
    (config.DATA / "checked-by-eye.json").write_text('{"%s": "a statue"}' % first)
    monkeypatch.setattr(demo, "look_for_people", lambda: {first: (1, 0)})
    demo.cmd_demo_check(Namespace(real=str(real)))
    assert "looked at: " + first in capsys.readouterr().out


def test_approved_places_are_allowed_but_only_those(con, tmp_path, capsys):
    real = tmp_path / "real"; real.mkdir()
    shutil.copy(config.DB, real / "index.sqlite")
    con.execute("insert into meta values('library', '/Users/x/Pictures/Photosearch Demo.photoslibrary')"); con.commit()
    (config.DATA / "approved-places.json").write_text('{"Portland": "fine to show"}')
    with pytest.raises(SystemExit):
        demo.cmd_demo_check(Namespace(real=str(real)))
    out = capsys.readouterr().out
    assert "'Portland'" not in out and "shows 'Sam'" in out  # names are never approvable this way
