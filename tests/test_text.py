"""The words in photos (text.py): read once per photo, and searched with "quotes"."""
import pytest

from photosearch import search, text


def write(con, said):
    con.executemany("insert or replace into texts values(?,?,'')", said.items()); con.commit()


def test_quotes_keep_to_photos_with_the_words_written_in_them(lib, con):
    write(con, {lib["dog1"]: "HAPPY BIRTHDAY\nRex", lib["cake2"]: "Happy Birthday Sam", lib["snow0"]: ""})
    assert {r["uuid"] for r in search.search(con, '"happy birthday"')} == {lib["dog1"], lib["cake2"]}
    assert search.search(con, 'a dog "birthdays"')[0]["uuid"] == lib["dog1"]  # the rest of the search ranks them
    assert search.search(con, '"happy holidays"') == []  # every word must be there


def test_searches_without_quotes_are_unchanged(lib, con):
    plain = [r["uuid"] for r in search.search(con, "a dog")]
    write(con, {lib["snow0"]: "Beware of the dog"})
    assert [r["uuid"] for r in search.search(con, "a dog")] == plain


def test_quotes_can_be_curly():
    assert text.quoted("the “Costco” receipt from \"Saanich\"") == (["Costco", "Saanich"], "the receipt from")
    assert text.quoted("no quotes here") == ([], "no quotes here")


def test_each_photo_is_read_once(lib, con, monkeypatch):
    seen = []
    monkeypatch.setattr(text, "read", lambda path: seen.append(path) or (["EXIT"] if lib["snow1"] in str(path) else []))
    text.read_all(con)
    photos = con.execute("select count(*) from photos where kind='photo'").fetchone()[0]
    assert len(seen) == photos  # not the video
    assert dict(con.execute("select uuid, text from texts where text != ''")) == {lib["snow1"]: "EXIT"}
    seen.clear(); text.read_all(con)
    assert seen == []
    assert text.written_in(con, ["exit"]) == {lib["snow1"]}


def test_a_stuck_reader_costs_one_photo(monkeypatch, readings, tmp_path):
    """Vision once stopped answering mid-run: a photo that takes too long is left for next time, and a new reader goes
    on with the rest. Three stuck in a row: Vision isn't answering anyone, so stop for this run."""
    import sys
    fake = tmp_path / "reader.py"  # a stand-in for `photosearch read-text`
    fake.write_text("import json, sys, time\n"
                    "for f in sys.argv[1:]:\n"
                    "    if 'stuck' in f: time.sleep(60)\n"
                    "    print(json.dumps(None if 'bad' in f else [f.upper()]), flush=True)\n")
    monkeypatch.setattr(text, "READER", [sys.executable, str(fake)])
    monkeypatch.setattr(text, "WAIT", 1); monkeypatch.setattr(text, "BATCH", 3)
    jobs = [(x, x) for x in ("a", "stuck", "b", "bad", "c", "d", "e")]
    assert list(readings(jobs)) == [("a", ["A"]), ("stuck", None), ("b", ["B"]), ("bad", None), ("c", ["C"]),
                                    ("d", ["D"]), ("e", ["E"])]
    out = []
    with pytest.raises(TimeoutError):
        for r in readings([("a", "a")] + [(f"stuck{i}", f"stuck{i}") for i in range(4)]):
            out.append(r)
    assert out == [("a", ["A"]), ("stuck0", None), ("stuck1", None), ("stuck2", None)]


def test_index_goes_on_when_vision_stops_answering(lib, con, monkeypatch, capsys):
    def stuck(jobs):
        yield jobs[0][0], ["EXIT"]
        raise TimeoutError
    monkeypatch.setattr(text, "readings", stuck)
    text.read_all(con)
    assert con.execute("select count(*) from texts").fetchone()[0] == 1
    assert "stopped answering" in capsys.readouterr().out
