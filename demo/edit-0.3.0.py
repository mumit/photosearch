"""Cuts what's new in photosearch 0.3.0: ✨ smart search from the web take, then a 📖 photo book of the demo library's
Alberta trip, made by the released 0.3.0 (`photosearch book`) and shown page by page, with a title card and an end card.

    reshoot edit edit-0.3.0.py takes/web-0.3.0.mp4 [OUT_DIR]

Writes whats-new-0.3.0.mp4, smart-search.mp4 and .gif, photo-book.mp4 and .gif, and the book's PDF, to OUT_DIR
(default: next to the web take). Every page of the book comes from the demo library, and is checked with the rest.
"""
import os, re, subprocess, sys, tempfile
from pathlib import Path

from reshoot import cut

W, H = 1920, 1080
BG = (14, 13, 12)  # the page's dark theme
STORY = "trip-2026-05-15"  # the demo library's one trip: Alberta
PAGES = 4  # the cover and the first pages after it
PAGE_SECONDS = 2.2
TITLE = ("What’s new in photosearch 0.3.0", "Search your photos by what’s in them · on your Mac")
BOOK = ("Any trip or year, as a photo book", "a PDF ready to print · photos fitted, never cropped")
END = ("photosearch", "uv tool install photosearch", "open source · github.com/mumit/photosearch")
DEMO = Path(__file__).resolve().parent.parent / "data-demo"


def book_pages(t):
    """The first PAGES pages of the demo trip's photo book, as PNGs on the page's dark background, 1920 x 1080."""
    from PIL import Image
    import io
    pdf = t / "book.pdf"
    env = dict(os.environ, PHOTOSEARCH_DATA=str(DEMO))
    subprocess.run(["uvx", "--from", "photosearch==0.3.0", "photosearch", "book", STORY, "--out", str(pdf)],
                   env=env, check=True)
    data = pdf.read_bytes()
    out = []
    for i, m in enumerate(re.finditer(rb"/DCTDecode /Length (\d+) >>\nstream\n", data)):
        if i == PAGES:
            break
        page = Image.open(io.BytesIO(data[m.end():m.end() + int(m.group(1))])).convert("RGB")
        page.thumbnail((W - 160, H - 220))
        frame = Image.new("RGB", (W, H), BG)
        frame.paste(page, ((W - page.width) // 2, 60))
        out.append(frame)
    return pdf, out


def main(web, out=None):
    web = Path(web)
    out = Path(out) if out else web.parent
    out.mkdir(parents=True, exist_ok=True)
    b = cut.beats(web)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        ww, _, _ = cut.probe(web)
        smart = cut.trim(web, 0, b["end"] + 0.6, t / "smart.mp4", fade_in=0.3, fade_out=0.4)
        if ww != W:
            smart = cut.place(cut.Card(W, H, BG).save(t / "black.png"), smart, 0, 0, t / "smart-big.mp4", width=W)
        cut.concat([smart], out / "smart-search.mp4")
        cut.gif(web, b["type1"], b["end"], out / "smart-search.gif", fps=10, width=720)  # under 10 MB, for X

        pdf, pages = book_pages(t)
        (out / "photo-book.pdf").write_bytes(pdf.read_bytes())
        book = []
        for i, frame in enumerate(pages):
            c = cut.Card(W, H, BG)
            c.im.paste(frame, (0, 0))
            c.text(None, H - 130, BOOK[0] if i == 0 else BOOK[1], 44 if i == 0 else 36, 600 if i == 0 else 500,
                   (240, 240, 240) if i == 0 else (205, 205, 205))
            book.append(cut.still(c.save(t / f"page{i}.png"), PAGE_SECONDS, t / f"page{i}.mp4", fade_in=0.3))
        book = cut.concat(book, out / "photo-book.mp4")
        cut.gif(book, 0, cut.duration(book), out / "photo-book.gif", fps=8, width=800)

        title = cut.Card(W, H, BG).text(None, 430, TITLE[0], 84, 700).text(None, 560, TITLE[1], 40, 500, (210, 210, 210))
        end = (cut.Card(W, H, BG).text(None, 380, END[0], 112, 700).text(None, 540, END[1], 48, 600, (245, 180, 60))
               .text(None, 640, END[2], 36, 500, (200, 200, 200)))
        cut.concat([cut.still(title.save(t / "title.png"), 2.5, t / "title.mp4"), smart, book,
                    cut.still(end.save(t / "end.png"), 3.5, t / "end.mp4")], out / "whats-new-0.3.0.mp4")
    for f in [out / "whats-new-0.3.0.mp4", out / "smart-search.mp4", out / "smart-search.gif", out / "photo-book.mp4",
              out / "photo-book.gif"]:
        print(f"  {f}  {cut.duration(f):5.1f}s  {f.stat().st_size / 1e6:4.1f} MB")


if __name__ == "__main__":
    main(*sys.argv[1:])
