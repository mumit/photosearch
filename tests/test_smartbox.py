"""The ✨ smart search box (smartbox.py): Jev reads filters out of the words with a key, keyword rules without one."""
from datetime import date

import pytest

from photosearch import smartbox

TODAY = date(2026, 11, 22)


def test_without_a_key_the_rules_read_it(con, monkeypatch):
    monkeypatch.setattr(smartbox, "ask_jev", lambda text: pytest.fail("Jev was asked without a key"))
    f, by = smartbox.parse_query(con, "videos of Sam in the snow last year, no people", today=TODAY)
    assert by == "rules"
    assert f == dict(person="Sam", kind="video", after="2025-01-01", before="2026-01-01", season="", exclude="people")


@pytest.mark.parametrize("words, kind, season, when, exclude", [
    ("movie night with popcorn", "", "", {}, ""),  # a movie night isn't a video
    ("fall colours on the trail, just scenery", "", "autumn", {}, "people"),
    ("that video where someone fell off the trampoline", "video", "", {}, ""),  # fell isn't the season
    ("selfies with someone at the concert", "", "", {}, ""),  # wants selfies
    ("group photo at the wedding but not selfies please", "", "", {}, "a selfie"),
    ("only photos of the waterfall from 2019", "photo", "", dict(after="2019-01-01", before="2020-01-01"), ""),
    ("recent pics of the garden", "", "", dict(after="2026-07-25"), ""),
    ("pictures from when the kids were little", "", "", dict(before="2021-11-22"), ""),
    ("christmas morning when someone was a toddler", "", "", dict(before="2021-11-22"), ""),
    ("winter skiing pics 2023 not the videos", "photo", "winter", dict(after="2023-01-01", before="2024-01-01"), ""),
    ("thanksgiving dinner last yr", "", "", dict(after="2025-01-01", before="2026-01-01"), ""),
    ("videos of the kids at the beach last summer", "video", "summer", dict(after="2026-01-01"), ""),  # this year's
])
def test_what_the_rules_read(con, words, kind, season, when, exclude):
    f, _ = smartbox.parse_query(con, words, today=TODAY)
    assert (f["kind"], f["season"], {k: f[k] for k in ("after", "before") if f[k]}, f["exclude"]) == (kind, season, when, exclude)


def test_last_summer_is_the_latest_one_thats_over():
    when = lambda words, day: smartbox.read_words(words, day)["when"]["choice"]
    assert when("last summer", date(2026, 11, 22)) == "this year" and when("last summer", date(2027, 4, 1)) == "last year"
    assert when("last winter", date(2026, 11, 22)) == "this year" and when("last winter", date(2027, 1, 15)) == "last year"


def jev_answers(kind="either", season="none", when="any", no_people=0.0, no_selfies=0.0):
    c = lambda x: dict(choice=x, confidence=0.9)
    return dict(kind=c(kind), season=c(season), when=c(when), no_people=dict(noul=no_people), no_selfies=dict(noul=no_selfies))


def test_with_a_key_jev_reads_it_without_names(con, monkeypatch):
    sent = []
    monkeypatch.setattr(smartbox, "jev_key", lambda: "test-key")
    monkeypatch.setattr(smartbox, "ask_jev", lambda text: sent.append(text) or jev_answers(season="summer", no_selfies=0.9))
    f, by = smartbox.parse_query(con, "Sam on the beach in the warm months, none of me", today=TODAY)
    assert by == "jev" and sent == ["someone on the beach in the warm months, none of me"]
    assert (f["person"], f["season"], f["exclude"]) == ("Sam", "summer", "a selfie")


def test_when_jev_cant_answer_the_rules_do(con, monkeypatch):
    def offline(text):
        raise OSError("offline")
    monkeypatch.setattr(smartbox, "jev_key", lambda: "test-key")
    monkeypatch.setattr(smartbox, "ask_jev", offline)
    f, by = smartbox.parse_query(con, "winter videos, no selfies", today=TODAY)
    assert by == "rules" and (f["kind"], f["season"], f["exclude"]) == ("video", "winter", "a selfie")

