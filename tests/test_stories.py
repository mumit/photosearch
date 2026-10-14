import json

import pytest

from photosearch import stories


def test_a_trip_story_is_told_day_by_day(con):
    r = stories.load_review(con, "trip-2025-03-10", make=True)
    assert r["title"] == "Lisbon" and r["made_by"] == "auto" and r["intro"].startswith("March 10–14, 2025")
    assert [c["title"] for c in r["chapters"]] == [f"Day {d} · Lisbon" for d in range(1, 6)]
    assert (stories.REVIEWS / "trip-2025-03-10.json").exists()


def test_a_year_story_by_month(con):
    r = stories.auto_review(con, "2024")
    assert r["kind"] == "year" and all(c["title"] in stories.MONTHS for c in r["chapters"])


@pytest.mark.parametrize("rid", ["../albums/x", "trip-2025-3-1", "20255", "", "trip-2099-01-01"])
def test_bad_story_ids(con, rid):
    with pytest.raises(LookupError):
        stories.story_span(con, rid)


def test_editing_keeps_claudes_name_but_marks_it_edited(con):
    r = stories.auto_review(con, "2024")
    stories.save_review(dict(r, made_by="claude"))
    uuid = r["chapters"][0]["photos"][0]["uuid"]
    out = stories.edit_review(con, dict(id="2024", chapters=[dict(title="", photos=[dict(uuid=uuid, caption="x" * 999)])]))
    assert out == dict(photos=1, chapters=1, made_by="claude")
    saved = stories.load_review(con, "2024")
    assert saved["edited"] and saved["chapters"][0]["title"] == "Untitled" and len(saved["chapters"][0]["photos"][0]["caption"]) == 300


def test_stories_list_trips_then_years(con):
    s = stories.stories(con)
    assert s[0]["id"] == "trip-2025-03-10" and s[0]["kind"] == "trip"
    assert [x["id"] for x in s if x["kind"] == "year"] == [str(y) for y in range(2025, 2017, -1)]


def test_render_inlines_photos_for_sending(con):
    r = stories.load_review(con, "trip-2025-03-10", make=True)
    page = stories.render_review(con, r, embed=True)
    assert page.count("data:image/jpeg;base64,") == sum(len(c["photos"]) for c in r["chapters"])
    data = json.loads(page.split("const R = ", 1)[1].split(";\n", 1)[0])
    assert data["title"] == "Lisbon" and data["kicker"] == "March 10–14, 2025"


def test_captions_cant_break_out_of_the_page(con):
    r = stories.load_review(con, "trip-2025-03-10", make=True)
    r["chapters"][0]["photos"][0]["caption"] = "</script><script>alert(1)</script>"
    page = stories.render_review(con, r)
    assert "</script><script>alert(1)" not in page


@pytest.mark.parametrize("a, b, text", [
    ("2026-08-10", "2026-08-10", "August 10, 2026"),
    ("2026-08-10", "2026-08-18", "August 10–18, 2026"),
    ("2026-08-30", "2026-09-02", "August 30 – September 2, 2026"),
    ("2025-12-30", "2026-01-02", "December 30, 2025 – January 2, 2026"),
])
def test_date_range(a, b, text):
    assert stories.date_range(a, b) == text


def test_export_names():
    assert stories.export_name(dict(kind="year", id="2025")) == "year-in-review-2025.html"
    assert stories.export_name(dict(kind="trip", title="São Paulo!", start="2024-05-02")) == "sao-paulo-2024.html"
