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


def test_automatic_stories_follow_the_library(con):
    r = stories.load_review(con, "trip-2025-03-10", make=True)
    stories.save_review(dict(r, title="Trip"))  # saved before Photos had named the place, say
    assert stories.load_review(con, "trip-2025-03-10")["title"] == "Lisbon"
    assert next(s for s in stories.stories(con) if s["id"] == "trip-2025-03-10")["title"] == "Lisbon"


def test_an_automatic_story_of_a_trip_that_no_longer_is_goes(con):
    stories.save_review(dict(id="trip-2019-01-01", kind="trip", start="2019-01-01", end="2019-01-02", title="Gone",
                             made_by="auto", chapters=[]))
    assert "trip-2019-01-01" not in {s["id"] for s in stories.stories(con)}
    with pytest.raises(LookupError):
        stories.load_review(con, "trip-2019-01-01")


def test_stories_you_or_claude_made_are_kept_as_made(con):
    r = stories.load_review(con, "trip-2025-03-10", make=True)
    stories.save_review(dict(r, title="Our week in Lisbon", made_by="claude"))
    assert stories.load_review(con, "trip-2025-03-10")["title"] == "Our week in Lisbon"


def connected(name, title=None):
    """A request from an agent's app, as the MCP server sees it: just the name it gave on connecting."""
    from types import SimpleNamespace as N
    return N(session=N(client_params=N(client_info=N(name=name, title=title))))


@pytest.mark.parametrize("ctx, by", [(connected("cursor"), "cursor"), (connected("claude-code", "Claude Code"), "Claude Code"),
                                     (None, None)])
def test_a_story_an_agent_saves_carries_its_name(con, ctx, by):
    from photosearch import mcp_server
    r = stories.auto_review(con, "2024")
    mcp_server.save_story("2024", "Our year", "", r["chapters"], ctx=ctx)
    listed = next(s for s in stories.stories(con) if s["id"] == "2024")
    assert (listed["made_by"], listed["agent"]) == ("agent", by)
    uuid = r["chapters"][0]["photos"][0]["uuid"]
    stories.edit_review(con, dict(id="2024", chapters=[dict(title="", photos=[dict(uuid=uuid, caption="")])]))
    saved = stories.load_review(con, "2024")
    assert (saved["made_by"], saved["agent"], saved["edited"]) == ("agent", by, True)


def test_agents_context_isnt_a_tool_argument():
    from photosearch import mcp_server
    tools = {t.name: t for t in mcp_server.mcp._tool_manager.list_tools()}
    for name in ("save_story", "eval_sheet", "score_eval_sheet"):
        assert "ctx" not in tools[name].parameters["properties"]


def test_an_agent_asks_before_replacing_your_story(con):
    from photosearch import mcp_server
    r = stories.auto_review(con, "2024")
    stories.save_review(dict(r, title="Ours", made_by="you"))
    with pytest.raises(ValueError, match="ask them"):
        mcp_server.save_story("2024", "The agent's", "", r["chapters"])
    assert stories.load_review(con, "2024")["title"] == "Ours"
    mcp_server.save_story("2024", "The agent's", "", r["chapters"], replace=True)
    assert stories.load_review(con, "2024")["title"] == "The agent's"
    mcp_server.save_story("2024", "Again", "", r["chapters"])  # its own story: no need to ask


def own_story(lib, name="story-sam-over-the-years"):
    from photosearch import mcp_server
    chapters = [dict(title="Early on", photos=[dict(uuid=lib["dog1"], caption="Alex and the dog")]),
                dict(title="Lately", photos=[dict(uuid=lib["portrait"], caption="Sam")])]
    return mcp_server.save_story(name, "Sam over the years", "", chapters)


def test_a_story_of_any_photos_spans_its_photos(con, lib):
    own_story(lib)
    s = stories.stories(con)[0]
    assert (s["id"], s["kind"], s["start"], s["end"], s["photos"]) == ("story-sam-over-the-years", "own", "2020-02-05", "2025-05-05", 2)
    r = stories.load_review(con, "story-sam-over-the-years")
    assert stories.kicker(r) == "2020 – 2025" and stories.export_name(r) == "sam-over-the-years.html"
    assert stories.kicker(dict(r, start="2025-03-01", end="2025-05-05")) == "March 1 – May 5, 2025"


def test_editing_a_story_of_any_photos_moves_its_days(con, lib):
    own_story(lib)
    stories.edit_review(con, dict(id="story-sam-over-the-years", chapters=[dict(title="x", photos=[dict(uuid=lib["beach0"])])]))
    r = stories.load_review(con, "story-sam-over-the-years")
    assert (r["start"], r["end"], r["made_by"], r["edited"]) == ("2018-07-10", "2018-07-10", "agent", True)


def test_photos_for_a_story_of_any_photos_come_from_the_whole_library(con, lib):
    own_story(lib)
    days = {p["date"][:4] for p in stories.story_candidates(con, "story-sam-over-the-years")}
    assert "2018" in days and "2025" in days  # not just its own 2020 to 2025


@pytest.mark.parametrize("rid", ["story-Sam", "story-../reviews/2024", "story-", "story-a--b"])
def test_bad_names_for_a_story_of_any_photos(con, lib, rid):
    with pytest.raises(ValueError):
        own_story(lib, rid)
    assert not any(stories.REVIEWS.glob("story-*"))


def test_a_story_of_any_photos_is_never_made_automatically(con):
    with pytest.raises(LookupError, match="no story"):
        stories.load_review(con, "story-nobody", make=True)
