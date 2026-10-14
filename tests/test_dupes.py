"""Near-duplicates. The made-up library holds four real groups and several traps; see tests/library.py."""
import pytest

from photosearch import config, dupes

REAL = [{"burst0", "burst1", "burst2"}, {"receiptcopy0", "receiptcopy1"}, {"copy0", "copy1"}, {"chain0", "chain1"}]


def groups(lib, con, level="same"):
    inv = {v: k for k, v in lib.items()}
    return [{inv[u] for u in g["uuids"]} for g in dupes.dupe_groups(con, level)]


@pytest.mark.parametrize("level", ["same", "similar"])
def test_finds_exactly_the_real_groups(lib, con, level):
    assert sorted(map(sorted, groups(lib, con, level))) == sorted(map(sorted, REAL))


def test_different_receipts_are_not_duplicates(lib, con):
    assert not any({"receipt0", "receipt1"} <= g for g in groups(lib, con))


def test_different_screenshots_are_not_duplicates(lib, con):
    assert not any({"screen0", "screen1"} <= g for g in groups(lib, con))


def test_look_alikes_years_apart_are_not_copies(lib, con):
    assert not any({"alike0", "alike1"} <= g for g in groups(lib, con))


def test_groups_dont_chain(lib, con):
    assert not any({"chain0", "chain2"} <= g for g in groups(lib, con))


def test_copies_years_apart_are_found(lib, con):
    g = next(g for g in dupes.dupe_groups(con) if lib["copy0"] in g["uuids"])
    assert g["kind"] == "copy"


def test_the_guards_matter(lib, con, monkeypatch):
    """Without the pixel check, the receipts and screenshots would be offered for deletion: so the tests above test it."""
    monkeypatch.setattr(dupes, "same_pixels", lambda a, b: True)
    found = groups(lib, con)
    assert any({"receipt0", "receipt1"} <= g for g in found) and any({"screen0", "screen1"} <= g for g in found)


def test_keeps_the_sharpest(lib, con):
    page = dupes.dupes(con)
    burst = next(g for g in page["groups"] if lib["burst0"] in {p["uuid"] for p in g["photos"]})
    assert (burst["keep"], burst["why"]) == (lib["burst0"], "the sharpest")
    assert (page["total"], page["extra"]) == (4, 5)
    assert (config.DATA / "sharpness.json").exists()


def test_your_pick_wins(lib, con):
    key = next(g["key"] for g in dupes.dupe_groups(con) if lib["burst0"] in g["uuids"])
    dupes.dupes_choose(con, dict(key=key, action="keep", uuid=lib["burst2"]))
    g = next(g for g in dupes.dupes(con)["groups"] if g["key"] == key)
    assert (g["keep"], g["why"]) == (lib["burst2"], "your pick")


def test_not_duplicates_hides_a_group(lib, con):
    key = next(g["key"] for g in dupes.dupe_groups(con) if lib["chain0"] in g["uuids"])
    dupes.dupes_choose(con, dict(key=key, action="nope"))
    assert key not in {g["key"] for g in dupes.dupes(con)["groups"]} and dupes.dupes(con)["total"] == 3


def test_choose_needs_an_action(con):
    with pytest.raises(ValueError):
        dupes.dupes_choose(con, dict(key="x", action="delete"))


def test_send_puts_only_the_extras_in_the_maybe_delete_album(lib, con, photos_app):
    nope = next(g["key"] for g in dupes.dupe_groups(con) if lib["chain0"] in g["uuids"])
    dupes.dupes_choose(con, dict(key=nope, action="nope"))
    assert dupes.dupes_send(con)["added"] == 4
    [(album, sent)] = photos_app.added
    inv = {v: k for k, v in lib.items()}
    assert album == dupes.MAYBE_DELETE
    assert {inv[u] for u in sent} >= {"burst1", "burst2"} and len(sent) == 4  # one of each identical pair
    assert not {lib["burst0"], lib["chain0"], lib["chain1"]} & set(sent)  # never the keeper, never a group marked not duplicates
    assert all(p["sent"] for g in dupes.dupes(con)["groups"] for p in g["photos"] if p["uuid"] in sent)


def test_send_twice_sends_nothing_new(con, photos_app):
    dupes.dupes_send(con)
    assert dupes.dupes_send(con)["added"] == 0
    assert photos_app.added[-1][1] == []


def test_pages(con):
    a, b = dupes.dupes(con, limit=2), dupes.dupes(con, offset=2, limit=2)
    assert len(a["groups"]) == len(b["groups"]) == 2
    assert not {g["key"] for g in a["groups"]} & {g["key"] for g in b["groups"]}


def test_a_missing_thumbnail_isnt_a_crash(lib, con):
    (config.THUMBS / f"{lib['receiptcopy1']}.jpg").unlink()
    assert not any({"receiptcopy0", "receiptcopy1"} <= g for g in groups(lib, con))
