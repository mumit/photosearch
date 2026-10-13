"""photosearch as an MCP server: lets Claude search your Photos library, look at the results, and make albums.

  claude mcp add photosearch -- uv run --directory /path/to/photosearch python mcp_server.py

Reads the index built by `ps.py index`; only make_album changes anything in Photos (and it never removes).
"""
import json
from collections import Counter
from typing import Literal, TypedDict

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
    info = ps.photo_info(con, uuids)
    missing = [u for u in uuids if u not in info]
    uuids = [u for u in uuids if u in info]
    if size == "large":
        out = [Image(data=ps.photo_jpeg(con, u), format="jpeg") for u in uuids[:4]]
        return out + [json.dumps(tidy([info[u] for u in uuids[:4]]) + ([{"not indexed": missing}] if missing else []))]
    uuids = uuids[:SHEET_MAX]
    sheet = ps.contact_sheet(con, uuids, cell=CELL)
    key = [dict(n=n + 1, uuid=u, date=info[u]["date"], place=info[u]["place"]) for n, u in enumerate(uuids)]
    return [Image(data=sheet, format="jpeg"), json.dumps(key + ([{"not indexed": missing}] if missing else []))]


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


class ReviewPhoto(TypedDict):
    uuid: str
    caption: str


class Chapter(TypedDict, total=False):
    title: str
    text: str
    photos: list[ReviewPhoto]


@mcp.tool(annotations=READ)
def year_highlights(year: int, count: int = 40) -> list:
    """Candidates for a year in review: a varied set of the year's best photos (near-duplicates removed, spread
    across events), in date order, as numbered contact sheets plus their dates, places and people."""
    h = ps.year_highlights(con, year, min(count, 60))
    if not h:
        return [f"no photos indexed for {year}"]
    out = [Image(data=ps.contact_sheet(con, [x["uuid"] for x in h[i:i + SHEET_MAX]], cell=CELL), format="jpeg")
           for i in range(0, len(h), SHEET_MAX)]
    key = [dict(n=n + 1, **{k: v for k, v in x.items() if k in ("uuid", "date", "place", "persons", "event") and v not in ("", [])})
           for n, x in enumerate(h)]
    return out + [json.dumps(key, ensure_ascii=False)]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def save_year_review(year: int, title: str, intro: str, chapters: list[Chapter], outro: str = "") -> str:
    """Save a year in review and get the link to its slideshow. Pick ~20-30 photos from year_highlights (look at
    them first: skip blurry shots, near-repeats, receipts and too many selfies), group them into 4-8 chapters in
    date order with short titles, and give each photo a one-line caption. Captions should describe what's in the
    photo, using only names from the photo's tagged people; don't invent events or feelings. Replaces any earlier
    review for that year (the automatic one included)."""
    known = ps.photo_info(con, [p["uuid"] for c in chapters for p in c.get("photos", [])])
    bad = [p["uuid"] for c in chapters for p in c.get("photos", []) if p["uuid"] not in known]
    if bad:
        raise ValueError(f"not in the index: {bad}")
    ps.save_review(dict(year=year, title=title, intro=intro, outro=outro, made_by="claude", chapters=chapters))
    n = sum(len(c.get("photos", [])) for c in chapters)
    return (f"saved {n} photos in {len(chapters)} chapters. Slideshow: http://localhost:8765/review/{year} "
            f"(needs `ps.py serve`). One-file copy to share: `uv run python ps.py review {year} --export {year}.html`")


if __name__ == "__main__":
    mcp.run()
