"""Reading photos from disk and writing JPEGs."""
import io

from .config import DISPLAY_PX, LARGE, THUMBS


def open_image(path, px=1024):
    """The image, upright, in RGB, at most px on its long side (1024 is plenty for the model)."""
    from PIL import Image, ImageOps
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((px, px))
    return im


def photo_jpeg(con, uuid, px=DISPLAY_PX, quality=85):
    """The photo as a JPEG at most px on its long side: from its full-size copy if one was fetched, else from the
    best local preview (which, for photos kept only in iCloud, can be as small as 256 px)."""
    row = con.execute("select src from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(uuid)
    big = LARGE / f"{uuid}.jpg"
    if big.exists() and px >= DISPLAY_PX:
        return big.read_bytes()
    buf = io.BytesIO()
    open_image(big if big.exists() else row[0], px).save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def contact_sheet(con, uuids, cols=6, cell=200):
    """One JPEG of numbered thumbnails (1..n in the order given), for Claude to look at many photos at once."""
    from PIL import Image, ImageDraw, ImageFont
    cols = min(cols, len(uuids)) or 1
    sheet = Image.new("RGB", (cols * cell, -(-len(uuids) // cols) * cell), "white")
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default(size=26)
    for n, u in enumerate(uuids):
        im = Image.open(THUMBS / f"{u}.jpg")
        im.thumbnail((cell - 4, cell - 4))
        x, y = n % cols * cell, n // cols * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        draw.rectangle((x + 2, y + 2, x + 40, y + 34), fill="black")
        draw.text((x + 8, y + 4), str(n + 1), fill="white", font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return buf.getvalue()
