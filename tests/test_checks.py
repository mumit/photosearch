"""✨ smart search's second step (checks.py): Jev's yes/no on a search's first photos nudges their order."""
import pytest

from photosearch import checks, search, smartbox


@pytest.fixture
def jev(monkeypatch):
    """A Jev that says yes to the photos in jev.yes, and records what it was sent."""
    class Jev:
        yes, sent = set(), []
        def __call__(self, query, descriptions):
            self.sent.append((query, descriptions))
            return [1.0 if any(f"Photo #{u}" in d for u in self.yes) else 0.0 for d in descriptions]
    j = Jev()
    monkeypatch.setattr(smartbox, "jev_key", lambda: "test-key")
    monkeypatch.setattr(checks, "ask", j)
    monkeypatch.setattr(checks, "describe", lambda con, us: [f"Photo #{u}" for u in us])
    checks._asked.clear()
    return j


def test_a_yes_moves_a_photo_up_by_a_little(lib, con, jev):
    res = search.search(con, "a dog", 40)
    # the first photo whose score is within CHECK_W of the one above it can pass it
    i = next(i for i in range(1, len(res)) if res[i - 1]["score"] - res[i]["score"] < checks.CHECK_W)
    jev.yes = {res[i]["uuid"]}
    out, done = checks.check(con, "a dog", res)
    assert done and out.index(res[i]) < i
    assert {r["uuid"] for r in out} == {r["uuid"] for r in res}  # the same photos, reordered
    far = res[-1]
    jev.yes = {far["uuid"]}; checks._asked.clear()
    assert checks.check(con, "a dog", res)[0][0] == res[0]  # no yes beats a much better match


def test_jev_never_sees_a_name(lib, con, jev):
    checks.check(con, "Sam at the beach", search.search(con, "Sam at the beach", 40))
    assert jev.sent[-1][0] == "someone at the beach"


def test_photos_are_described_without_names_places_or_their_words(lib, con, monkeypatch):
    con.execute("insert into texts values(?, 'PASSPORT 12345', '')", (lib["lisbon2"],)); con.commit()
    d, = checks.describe(con, [lib["lisbon2"]])
    assert "Named people in it: 2" in d and "Image:" in d
    for private in ("Sam", "Alex", "Lisbon", "PASSPORT", "12345"):
        assert private not in d


def test_search_works_without_jev(lib, con, jev, monkeypatch):
    res = search.search(con, "a dog", 40)
    def down(query, descriptions):
        raise OSError("offline")
    monkeypatch.setattr(checks, "ask", down)
    assert checks.check(con, "a dog", res) == (res, False)
    monkeypatch.setattr(smartbox, "jev_key", lambda: None)
    assert checks.check(con, "a dog", res) == (res, False)


def test_asks_once_per_search(lib, con, jev):
    res = search.search(con, "snow", 40)
    checks.check(con, "snow", res); checks.check(con, "snow", res)
    assert len(jev.sent) == 1
