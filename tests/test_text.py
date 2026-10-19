"""The words in photos (text.py): read once per photo, and searched with "quotes"."""
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
