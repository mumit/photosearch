"""photosearch as an MCP server: lets Claude search your Photos library, look at the results, and make albums.

  claude mcp add photosearch -- uv run --directory /path/to/photosearch python mcp_server.py

Reads the index built by `ps.py index`; only make_album changes anything in Photos (and it never removes).
"""
import io
import json
from collections import Counter
from typing import Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

import ps

mcp = MCPServer("photosearch", instructions="""\
Search the user's Apple Photos library by what's in the pictures.
The search model compares text to pixels: good at scenes, objects, activities and mood; weak at negation
("no people"), counting, and reading text. So search for the positive thing, put what to avoid in `exclude`,
put names/places/dates in the filters (library_overview lists the names and places), then call view_photos on the candidates and keep only
the ones that actually match before answering or making an album. Refer to photos by date and place, not uuid.""")
con = ps.db()
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SHEET_MAX, CELL = 30, 200


def tidy(results):
    return [{k: (round(v, 3) if k == "score" else v) for k, v in r.items() if v not in ("", [], None) and k not in ("lat", "lon")}
            for r in results]


@mcp.tool(annotations=READ)
def search_photos(query: str, exclude: str | None = None, people: list[str] | None = None, place: str | None = None,
                  after: str | None = None, before: str | None = None, kind: Literal["photo", "video"] | None = None,
                  limit: int = 24) -> list[dict]:
    """Find photos by describing what's in them, e.g. "kids on a red slide at sunset", best match first.

    Put only the positive description in query; put what to avoid in exclude ("no selfies" -> exclude="a selfie").
    people: names that must all appear (substring match on the names tagged in Photos).
    place: substring of the place name, e.g. "Portland" or "Lisbon". after/before: ISO dates (YYYY-MM-DD).
    Scores only mean something relative to each other within one query.
    """
    return tidy(ps.search(con, query, min(limit, 200), exclude, person=people, place=place, after=after, before=before, kind=kind))


@mcp.tool(annotations=READ)
def similar_photos(uuid: str, people: list[str] | None = None, place: str | None = None, after: str | None = None,
                   before: str | None = None, limit: int = 24) -> list[dict]:
    """Photos that look like the given one (same scene, event, or subject), optionally filtered."""
    return tidy(ps.similar(con, uuid, min(limit, 200), person=people, place=place, after=after, before=before))


@mcp.tool(annotations=READ)
def best_per_year(query: str, per_year: int = 1) -> list[dict]:
    """The best match for a query in each year, e.g. "birthday cake" or "first day of school"."""
    return [dict(year=y["year"], photos=tidy(y["results"])) for y in ps.timeline(con, query, min(per_year, 5))]


@mcp.tool(annotations=READ)
def view_photos(uuids: list[str], size: Literal["sheet", "large"] = "sheet") -> list:
    """Look at photos. "sheet": one contact-sheet image of up to 30 thumbnails, numbered in the order given
    (use it to check search results). "large": up to 4 photos at full preview size, for detail."""
    from PIL import Image as PI, ImageDraw, ImageFont
    info = ps.photo_info(con, uuids)
    missing = [u for u in uuids if u not in info]
    uuids = [u for u in uuids if u in info]
    if size == "large":
        out = [Image(data=ps.photo_jpeg(con, u), format="jpeg") for u in uuids[:4]]
        return out + [json.dumps(tidy([info[u] for u in uuids[:4]]) + ([{"not indexed": missing}] if missing else []))]
    uuids = uuids[:SHEET_MAX]
    cols = min(6, len(uuids)) or 1
    sheet = PI.new("RGB", (cols * CELL, -(-len(uuids) // cols) * CELL), "white")
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default(size=26)
    for n, u in enumerate(uuids):
        im = PI.open(ps.THUMBS / f"{u}.jpg")
        im.thumbnail((CELL - 4, CELL - 4))
        x, y = n % cols * CELL, n // cols * CELL
        sheet.paste(im, (x + (CELL - im.width) // 2, y + (CELL - im.height) // 2))
        draw.rectangle((x + 2, y + 2, x + 40, y + 34), fill="black")
        draw.text((x + 8, y + 4), str(n + 1), fill="white", font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    key = [dict(n=n + 1, uuid=u, date=info[u]["date"], place=info[u]["place"]) for n, u in enumerate(uuids)]
    return [Image(data=buf.getvalue(), format="jpeg"), json.dumps(key + ([{"not indexed": missing}] if missing else []))]


@mcp.tool(annotations=READ)
def library_overview() -> dict:
    """What's indexed: photo/video counts, date range, the people tagged in Photos and the most common places.
    Use the exact names from here in search filters."""
    rows = con.execute("select kind, substr(date,1,10), persons, place from photos").fetchall()
    people = Counter(p for r in rows for p in json.loads(r[2]))
    places = Counter(r[3] for r in rows if r[3])
    dates = sorted(r[1] for r in rows)
    return dict(indexed=len(rows), kinds=Counter(r[0] for r in rows), first=dates[0] if dates else None,
                last=dates[-1] if dates else None, people=dict(people.most_common()), places=dict(places.most_common(40)))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def make_album(name: str, uuids: list[str]) -> str:
    """Add photos to an album in the Photos app, creating it if needed. Only adds; never removes or deletes.
    Check the photos with view_photos first."""
    from osxphotos.photosalbum import PhotosAlbum
    order = {u: i for i, u in enumerate(uuids)}
    photos = sorted(ps.photos_db().photos(uuid=list(order)), key=lambda p: order[p.uuid])
    PhotosAlbum(name).add_list(photos)
    return f"added {len(photos)} of {len(uuids)} photos to album '{name}'"


if __name__ == "__main__":
    mcp.run()
