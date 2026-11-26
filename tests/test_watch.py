"""While `serve` runs, the library is indexed by itself (watch.py), in an `index` process of its own."""
import os, subprocess

import pytest

from photosearch import index, store, watch


@pytest.fixture
def runs(monkeypatch):
    """The `index` commands watch would have run (none really run), and the environment they'd have had."""
    out = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: out.append((cmd, kw["env"])) or subprocess.CompletedProcess(cmd, 0))
    return out


def test_new_photos_are_indexed_in_a_process_of_their_own(lib, con, monkeypatch, runs):
    have = {u for (u,) in con.execute("select uuid from photos")}
    said = []
    monkeypatch.setattr(store, "library_uuids", lambda: set(have))
    monkeypatch.setattr(watch, "library_uuids", lambda: set(have))
    assert watch.check(con, said.append) == 0 and runs == []  # nothing new: nothing runs
    monkeypatch.setattr(watch, "library_uuids", lambda: have | {"NEW-1", "NEW-2"})
    assert watch.check(con, said.append) == 2
    assert [c for c, _ in runs] == [watch.COMMAND] and runs[0][0][-3:] == ["index", "--only-new", "--no-videos"]
    assert runs[0][1]["PHOTOSEARCH_STOP_WITH"] == str(os.getpid())  # it stops if serve goes
    assert said == ["indexing 2 new from Photos…", "indexed: they're in searches now"]


def test_photos_index_couldnt_read_arent_tried_every_time(lib, con, monkeypatch):
    have = {u for (u,) in con.execute("select uuid from photos")}
    con.execute("insert into skipped values ('ICLOUD-1', 'no preview on this Mac', '')"); con.commit()
    monkeypatch.setattr(watch, "library_uuids", lambda: have | {"ICLOUD-1"})
    assert watch.new_photos(con) == 0
    monkeypatch.setattr(watch, "library_uuids", lambda: None)  # no access to Photos
    assert watch.new_photos(con) == 0


def test_a_fresh_install_starts_its_first_index_quick(lib, con, monkeypatch, runs):
    con.execute("delete from photos"); con.execute("delete from meta where key='library'"); con.commit()
    monkeypatch.setattr(watch, "library_uuids", lambda: None)
    said = []
    watch.check(con, said.append)
    assert runs[0][0] == watch.FIRST_INDEX and runs[0][0][-2:] == ["index", "--quick"]
    assert said[0].startswith("nothing indexed yet") and said[1].startswith("the first index is done")
    assert watch.progress(con) == dict(job=None, since=watch.state["since"], photos=0, quick=0, library=None, error=None, hint=None)


def test_quick_photos_are_redone_once_nothings_new(lib, con, monkeypatch, runs):
    have = {u for (u,) in con.execute("select uuid from photos")}
    monkeypatch.setattr(watch, "library_uuids", lambda: set(have))
    con.execute("update photos set quick=1 where uuid in (select uuid from photos limit 5)"); con.commit()
    assert watch.job(con) == ("redo", 5, watch.REDO)
    monkeypatch.setattr(watch, "library_uuids", lambda: have | {"NEW-1"})
    assert watch.job(con)[0] == "new"  # new photos first


def test_why_an_index_stopped_is_shown(lib, con, monkeypatch):
    con.execute("delete from photos"); con.execute("delete from meta where key='library'"); con.commit()
    monkeypatch.setattr(watch, "library_uuids", lambda: None)

    def fails(cmd, stdout, **kw):
        stdout.write("opening Photos library…\nPermissionError: [Errno 1] Operation not permitted: 'Photos.sqlite'\n"); stdout.flush()
        return subprocess.CompletedProcess(cmd, 1)
    monkeypatch.setattr(subprocess, "run", fails)
    watch.check(con, lambda m: None)
    p = watch.progress(con)
    assert p["error"].startswith("PermissionError") and p["hint"] == "access"


def test_an_index_serve_started_stops_when_serve_goes(monkeypatch):
    gone = []
    monkeypatch.setattr(os, "getppid", lambda: 1)  # serve went, and launchd took the index on
    monkeypatch.setattr(os, "_exit", gone.append)
    index.stop_with(4321, every=0)
    assert gone == [1]
