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
