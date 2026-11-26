"""A story as a print-ready photo book (book.py): a PDF of 300 dpi pages, one JPEG each."""
import math, re

import pytest

from photosearch import book, stories


def check_pdf(data):
    """The PDF is whole: every object the cross-reference table points to is where it says. Returns its pages' boxes."""
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)", data).group(1))
    assert data[xref:].startswith(b"xref")
    offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", data[xref:])]
    for i, o in enumerate(offsets, 1):
        assert data[o:].startswith(b"%d 0 obj" % i)
    return re.findall(rb"/Type /Page /Parent.*?/MediaBox \[([^\]]*)\]( /TrimBox \[[^\]]*\])?", data)


def test_a_year_as_a_book(con):
    r = stories.load_review(con, "2025", make=True)
    data, low = book.book(con, r)
    pages = check_pdf(data)
    photos = [[p for p in c["photos"] if con.execute("select kind from photos where uuid=?", (p["uuid"],)).fetchone()[0] == "photo"]
              for c in r["chapters"]]
    photos = [c for c in photos if c]
    spare = next(i for i, c in enumerate(photos) if len(c) > 1)  # the cover comes from here, so isn't printed twice
    photos[spare] = photos[spare][1:]
    assert len(pages) == 1 + sum(1 + math.ceil((len(c) - 1) / 2) for c in photos)  # a cover, then 1 + pairs a chapter
    assert pages[0][0] == b"0 0 841.92 595.2" and not pages[0][1]  # landscape A4, no bleed
    assert low  # the made-up library's photos are small: each is listed as soft in print
    assert book.book_name(r) == "photo-book-2025.pdf"


def test_letter_with_a_bleed(con):
    data, _ = book.book(con, stories.load_review(con, "2025", make=True), size="letter", bleed=True)
    box, trim = check_pdf(data)[0]
    assert box == b"0 0 808.8 628.8" and trim == b" /TrimBox [8.4 8.4 800.4 620.4]"  # 11 x 8.5 in, and 3 mm all round
    with pytest.raises(ValueError):
        book.book(con, stories.load_review(con, "2025", make=True), size="a3")


def test_a_story_of_any_photos_as_a_book(con, lib):
    from photosearch import mcp_server
    mcp_server.save_story("story-the-dogs", "The dogs", "", [dict(title="Dogs", photos=[dict(uuid=lib[f"dog{i}"]) for i in range(4)])])
    data, _ = book.book(con, stories.load_review(con, "story-the-dogs"))
    assert len(check_pdf(data)) == 1 + 1 + 1  # a cover, the chapter's first photo, then the other two on a page
    assert book.book_name(stories.load_review(con, "story-the-dogs")) == "the-dogs.pdf"


def test_a_calendar_shows_each_month_of_the_year_before(con, lib):
    months = book.month_picks(con, 2025)
    dates = {u: d for u, d in con.execute("select uuid, date from photos")}
    month = [int(dates[m["uuid"]][5:7]) for m in months]
    assert month[:9] == list(range(1, 10)) and month[10] == 11  # from any year when 2025 has none
    assert dates[months[2]["uuid"]].startswith("2025-03")  # March 2025 had the Lisbon trip
    # no October or December in any year: the best of 2025 not on another month
    assert all(dates[months[i]["uuid"]].startswith("2025") for i in (9, 11)) and len({m["uuid"] for m in months}) == 12
    data, _ = book.wall_calendar(con, 2026, months)
    pages = check_pdf(data)
    assert len(pages) == 13 and pages[0][0] == b"0 0 595.2 841.92"  # a cover and 12 months, portrait A4
    with pytest.raises(ValueError, match="12 photos"):
        book.wall_calendar(con, 2026, months[:11])


def test_an_agent_prints_to_a_new_file(con, lib, tmp_path):
    import json
    from photosearch import mcp_server
    mcp_server.save_story("story-the-dogs", "The dogs", "", [dict(title="Dogs", photos=[dict(uuid=lib["dog0"])])])
    first = json.loads(mcp_server.make_book("story-the-dogs", folder=str(tmp_path)))
    again = json.loads(mcp_server.make_book("story-the-dogs", folder=str(tmp_path)))
    assert first["file"].endswith("the-dogs.pdf") and again["file"].endswith("the-dogs (2).pdf")
    assert first["soft"] and first["soft"][0]["date"]  # the made-up photos are small; listed as the agent can find them
    cal = json.loads(mcp_server.make_calendar(2026, folder=str(tmp_path)))
    assert cal["file"].endswith("calendar-2026.pdf") and len(check_pdf(open(cal["file"], "rb").read())) == 13
