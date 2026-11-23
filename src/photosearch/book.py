"""A story (a trip or a year) as a print-ready photo book: `photosearch book STORY`, or 📖 on a story.

A PDF of 300 dpi pages, landscape A4 or US Letter: a cover (the first photo across the page, with the title and
dates), then each chapter opening on its title, words and first photo, and the rest two to a page, each with its
caption, date and place under it. Photos are fitted, never cropped, except on the cover. Videos are left out.

Full-size copies are fetched from iCloud first where the local preview is small, and any photo that still prints under
LOW_DPI is listed, so it can be swapped out (✎) before printing. bleed=True adds the 3 mm a print shop trims off, and
marks the page's trimmed size (TrimBox). Each page goes in as one JPEG, written by a small PDF writer here, so a long
book never needs every page in memory at once."""
import io
from datetime import date
from pathlib import Path

from .config import LARGE
from .images import open_image
from .places import short_place
from .store import photo_info
from .stories import date_range, story_uuids

DPI = 300
SIZES = {"a4": (297, 210), "letter": (279.4, 215.9)}  # mm, landscape: most photos are
BLEED_MM, MARGIN_MM = 3, 14
LOW_DPI = 150  # under this, a print looks soft at arm's length
FONTS = Path("/System/Library/Fonts/Supplemental")
INK, MUTED, PAPER = (34, 31, 28), (120, 114, 106), (250, 248, 244)


def px(mm):
    return round(mm / 25.4 * DPI)


def font(size, style=""):
    """Georgia, as the stories' web pages use a serif; Pillow's own font where it's missing."""
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONTS / f"Georgia{' ' + style if style else ''}.ttf"), size)
    except OSError:
        return ImageFont.load_default(size=size)


def long_date(d):
    day = date.fromisoformat(d[:10])
    return f"{day.day} {day:%B %Y}"


def wrap(draw, text, f, width):
    """text in lines no wider than width."""
    lines, line = [], ""
    for word in text.split():
        if line and draw.textlength(f"{line} {word}", font=f) > width:
            lines.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


class Book:
    def __init__(self, con, size="a4", bleed=False):
        from PIL import Image
        if size not in SIZES:
            raise ValueError(f"size is {' or '.join(SIZES)}")
        self.con, self.bleed = con, px(BLEED_MM) if bleed else 0
        self.trim = tuple(px(mm) for mm in SIZES[size])
        self.W, self.H = (t + 2 * self.bleed for t in self.trim)
        self.margin = self.bleed + px(MARGIN_MM)
        self.pages, self.low, self.Image = [], {}, Image

    def page(self):
        from PIL import ImageDraw
        im = self.Image.new("RGB", (self.W, self.H), PAPER)
        return im, ImageDraw.Draw(im)

    def photo(self, uuid):
        """The photo at its best: the full-size copy if there is one, else the local preview."""
        src = self.con.execute("select src from photos where uuid=?", (uuid,)).fetchone()[0]
        big = LARGE / f"{uuid}.jpg"
        return open_image(big if big.exists() else src, 6000)

    def done(self, im):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90, dpi=(DPI, DPI))
        self.pages.append((buf.getvalue(), im.size))

    def cover(self, uuid, title, kicker):
        from PIL import ImageOps
        im, draw = self.page()
        pic = self.photo(uuid)
        self.check(uuid, pic, (self.W, self.H))
        im.paste(ImageOps.fit(pic, (self.W, self.H)), (0, 0))
        band = round(self.H * 0.24)
        shade = self.Image.new("RGB", (self.W, band), (20, 18, 16))
        im.paste(self.Image.blend(im.crop((0, self.H - band, self.W, self.H)), shade, 0.62), (0, self.H - band))
        draw.text((self.margin, self.H - band + px(9)), title, font=font(px(15)), fill=PAPER)
        draw.text((self.margin, self.H - band + px(29)), kicker, font=font(px(6), "Italic"), fill=(225, 220, 212))
        self.done(im)

    def check(self, uuid, pic, shown):
        """Note a photo that prints softer than LOW_DPI at the size shown."""
        dpi = round(min(pic.width / shown[0], pic.height / shown[1]) * DPI)
        if dpi < LOW_DPI:
            self.low[uuid] = min(dpi, self.low.get(uuid, dpi))

    def cell(self, im, draw, uuid, info, box):
        """A photo fitted into box (x, y, w, h), its caption, date and place under it."""
        x, y, w, h = box
        cap_h = px(11)
        pic = self.photo(uuid)
        scale = min(w / pic.width, (h - cap_h) / pic.height)
        size = (round(pic.width * scale), round(pic.height * scale))
        self.check(uuid, pic, size)
        left = x + (w - size[0]) // 2
        im.paste(pic.resize(size, self.Image.LANCZOS), (left, y))
        line = " · ".join(t for t in (info["caption"], long_date(info["date"]) if info["date"] else "", info["place"]) if t)
        f = font(px(3.6))
        while line and draw.textlength(line, font=f) > w:
            line = line[:-2].rstrip() + "…" if len(line) > 2 else ""
        draw.text((left, y + size[1] + px(2.5)), line, font=f, fill=MUTED)

    def chapter(self, title, text, photos):
        top, inner_w = self.margin, self.W - 2 * self.margin
        im, draw = self.page()
        draw.text((self.margin, top), title, font=font(px(9)), fill=INK)
        y = top + px(13)
        for line in wrap(draw, text, font(px(4.4), "Italic"), inner_w)[:3]:
            draw.text((self.margin, y), line, font=font(px(4.4), "Italic"), fill=MUTED); y += px(6.5)
        y += px(3)
        if photos:
            self.cell(im, draw, photos[0]["uuid"], photos[0], (self.margin, y, inner_w, self.H - self.margin - y))
        self.done(im)
        gap = px(8)
        for i in range(1, len(photos), 2):
            im, draw = self.page()
            pair = photos[i:i + 2]
            w = (inner_w - gap * (len(pair) - 1)) // len(pair)
            for j, p in enumerate(pair):
                self.cell(im, draw, p["uuid"], p, (self.margin + j * (w + gap), self.margin, w, self.H - 2 * self.margin))
            self.done(im)

    def pdf(self):
        """The pages as a PDF: each one JPEG, at its printed size, with the trimmed size marked if there's a bleed."""
        pt = lambda v: round(v * 72 / DPI, 2)
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None]
        kids = []
        for jpeg, (w, h) in self.pages:
            n = len(objs) + 1  # this page's number; its content and image follow it
            kids.append(f"{n} 0 R")
            b = self.bleed
            trim = f" /TrimBox [{pt(b)} {pt(b)} {pt(w - b)} {pt(h - b)}]" if b else ""
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pt(w)} {pt(h)}]{trim} "
                        f"/Resources << /XObject << /Im0 {n + 2} 0 R >> >> /Contents {n + 1} 0 R >>".encode())
            draw = f"q {pt(w)} 0 0 {pt(h)} 0 0 cm /Im0 Do Q".encode()
            objs.append(b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream")
            objs.append(f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
                        f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n".encode() + jpeg + b"\nendstream")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
        out, offsets = io.BytesIO(), []
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        for i, body in enumerate(objs, 1):
            offsets.append(out.tell())
            out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
        xref = out.tell()
        out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets))
        out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
        return out.getvalue()


def book(con, review, size="a4", bleed=False):
    """(the PDF's bytes, {uuid: dpi} of photos that print under LOW_DPI) for a story. Fetch full-size copies first."""
    info = photo_info(con, story_uuids(review))
    b = Book(con, size, bleed)
    chapters = [(c["title"], c.get("text", ""),
                 [dict(uuid=p["uuid"], caption=p.get("caption", ""), date=info[p["uuid"]]["date"],
                       place=short_place(info[p["uuid"]]["place"])) for p in c["photos"]
                  if p["uuid"] in info and info[p["uuid"]]["kind"] == "photo"]) for c in review["chapters"]]
    chapters = [c for c in chapters if c[2]]
    if not chapters:
        raise LookupError("this story has no photos to print")
    kicker = date_range(review["start"], review["end"]) if review.get("kind") == "trip" else "A year in photos"
    # the cover: the first photo of the first chapter with one to spare, so it isn't printed twice
    i = next((i for i, c in enumerate(chapters) if len(c[2]) > 1), None)
    b.cover(chapters[i or 0][2][0]["uuid"], review["title"], kicker)
    if i is not None:
        chapters[i] = (chapters[i][0], chapters[i][1], chapters[i][2][1:])
    for title, text, photos in chapters:
        b.chapter(title, text, photos)
    return b.pdf(), b.low


def book_name(review):
    from .stories import export_name
    return export_name(review).removesuffix(".html").replace("year-in-review", "photo-book") + ".pdf"


def cmd_book(a):
    from .photos_app import fetch_large, needs_fetch
    from .stories import load_review, STORY_ID
    from .store import db
    con = db()
    if not STORY_ID.fullmatch(a.story):
        raise SystemExit("a story is a year (2025) or a trip id from `photosearch trips` (trip-2024-05-02)")
    r = load_review(con, a.story, make=True)
    if need := [u for u in story_uuids(r) if needs_fetch(con, u)]:
        print(f"fetching full-size copies of {len(need)} photos from iCloud…")
        fetch_large(con, need, log=print)
    data, low = book(con, r, a.size, a.bleed)
    out = Path(a.out or book_name(r))
    out.write_bytes(data)
    print(f"wrote {out} ({len(data) / 1e6:.1f} MB): {r['title']}, {a.size.upper()} landscape"
          + (", with a 3 mm bleed" if a.bleed else ""))
    for u, dpi in sorted(low.items(), key=lambda x: x[1]):
        print(f"  soft in print ({dpi} dpi): {u}; swap it in the story editor (✎) if it matters")
