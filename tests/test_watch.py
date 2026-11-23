"""While `serve` runs, new photos are indexed by themselves (watch.py), in an `index` process of their own."""
import subprocess

from photosearch import store, watch


def test_new_photos_are_indexed_in_a_process_of_their_own(lib, con, monkeypatch):
    have = {u for (u,) in con.execute("select uuid from photos")}
    runs, said = [], []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: runs.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    monkeypatch.setattr(store, "library_uuids", lambda: set(have))
    monkeypatch.setattr(watch, "library_uuids", lambda: set(have))
    assert watch.check(con, said.append) == 0 and runs == []  # nothing new: nothing runs
    monkeypatch.setattr(watch, "library_uuids", lambda: have | {"NEW-1", "NEW-2"})
    assert watch.check(con, said.append) == 2
    assert runs == [watch.COMMAND] and runs[0][-3:] == ["index", "--only-new", "--no-videos"]
    assert said == ["indexing 2 new from Photos…", "indexed: they're in searches now"]


def test_photos_index_couldnt_read_arent_tried_every_time(lib, con, monkeypatch):
    have = {u for (u,) in con.execute("select uuid from photos")}
    con.execute("insert into skipped values ('ICLOUD-1', 'no preview on this Mac', '')"); con.commit()
    monkeypatch.setattr(watch, "library_uuids", lambda: have | {"ICLOUD-1"})
    assert watch.new_photos(con) == 0
    monkeypatch.setattr(watch, "library_uuids", lambda: None)  # no access to Photos
    assert watch.new_photos(con) == 0
