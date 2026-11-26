"""photosearch as an MCP server: lets an AI agent search your Photos library, look at the results, and make albums.
Any MCP client that starts local (stdio) servers and passes images to its model can use it. With Claude Code:

  claude mcp add photosearch -- uv run --directory /path/to/photosearch photosearch-mcp

Reads the index built by `photosearch index`; only make_album changes anything in Photos (and it never removes).
make_book and make_calendar write a PDF to print, by default in ~/Downloads.
"""
import json
from collections import Counter
from pathlib import Path
from typing import Literal, TypedDict

from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.types import ToolAnnotations

from . import config, evals, explore, images, photos_app, search, store, stories

mcp = MCPServer("photosearch", instructions="""\
Search the user's Apple Photos library by what's in the pictures.
The search model compares text to pixels: good at scenes, objects, activities and mood; weak at negation
("no people"), counting, and reading text. So search for the positive thing, put what to avoid in `exclude`,
put names/places/dates in the filters (library_overview lists the names and places), then call view_photos on the candidates and keep only
the ones that actually match before answering or making an album. Refer to photos by date and place, not uuid.""")
con = store.db()
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SHEET_MAX, CELL = 30, 200


def agent(ctx):
    """The agent's name, as its app gave it on connecting (Claude Code says "claude-code"), or None."""
    params = ctx and ctx.session.client_params
    return params and (params.client_info.title or params.client_info.name)


def judge_name(judge, ctx):
    """Who's judging: the name given, as given, else the agent's. Claude's apps all judge as "claude", as it did before
    other agents could, so its verdicts stay one judge's."""
    if not judge:
        name = (agent(ctx) or "agent").lower()
        judge = "claude" if name.startswith("claude") else name
    return evals.judge_key(judge)


def tidy(results):
    return [{k: (round(v, 3) if k == "score" else v) for k, v in r.items() if v not in ("", [], None) and k not in ("lat", "lon", "frame")}
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
    Words in double quotes must be written in the photo (signs, receipts, documents, as read by the Mac):
    '"Costco" receipt' finds receipts that say Costco. Use quotes only for exact words, since the model already reads
    big, clear text without them.
    Videos also match by what's heard in them ("people singing Happy Birthday", "a dog barking") and by later
    frames, once `photosearch videos` has read them: then "at" is the moment in seconds, and "heard" says it was a sound.
    """
    return tidy(search.search(con, query, min(limit, 200), exclude, person=people, place=place, after=after, before=before, kind=kind))


@mcp.tool(annotations=READ)
def similar_photos(uuid: str, people: list[str] | None = None, place: str | None = None, after: str | None = None,
                   before: str | None = None, limit: int = 24) -> list[dict]:
    """Photos that look like the given one (same scene, event, or subject), optionally filtered."""
    return tidy(search.similar(con, uuid, min(limit, 200), person=people, place=place, after=after, before=before))


@mcp.tool(annotations=READ)
def best_per_year(query: str, per_year: int = 1) -> list[dict]:
    """The best match for a query in each year, e.g. "birthday cake" or "first day of school"."""
    return [dict(year=y["year"], photos=tidy(y["results"])) for y in explore.timeline(con, query, min(per_year, 5))]


@mcp.tool(annotations=READ)
def view_photos(uuids: list[str], size: Literal["sheet", "large"] = "sheet") -> list:
    """Look at photos. "sheet": one contact-sheet image of up to 30 thumbnails, numbered in the order given
    (use it to check search results). "large": up to 4 photos at full preview size, for detail."""
    info = store.photo_info(con, uuids)
    missing = [u for u in uuids if u not in info]
    uuids = [u for u in uuids if u in info]
    if size == "large":
        out = [Image(data=images.photo_jpeg(con, u, 1024), format="jpeg") for u in uuids[:4]]
        return out + [json.dumps(tidy([info[u] for u in uuids[:4]]) + ([{"not indexed": missing}] if missing else []))]
    uuids = uuids[:SHEET_MAX]
    sheet = images.contact_sheet(con, uuids, cell=CELL)
    key = [dict(n=n + 1, uuid=u, date=info[u]["date"], place=info[u]["place"]) for n, u in enumerate(uuids)]
    return [Image(data=sheet, format="jpeg"), json.dumps(key + ([{"not indexed": missing}] if missing else []))]


@mcp.tool(annotations=READ)
def library_overview() -> dict:
    """What's indexed: photo/video counts, date range, the people tagged in Photos and the most common places.
    Use the exact names from here in search filters. "coverage" lists what search can't find yet (photos new
    since the last index or not indexed, videos not read, words not read), with the command that fixes each: mention it when a search comes up short."""
    rows = con.execute("select kind, substr(date,1,10), persons, place from photos").fetchall()
    people = Counter(p for r in rows for p in json.loads(r[2]))
    places = Counter(r[3] for r in rows if r[3])
    dates = sorted(r[1] for r in rows)
    return dict(indexed=len(rows), kinds=Counter(r[0] for r in rows), first=dates[0] if dates else None,
                last=dates[-1] if dates else None, people=dict(people.most_common()), places=dict(places.most_common(40)),
                coverage=store.coverage(con)["gaps"], data_folder=str(config.DATA))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def make_album(name: str, uuids: list[str]) -> str:
    """Add photos to an album in the Photos app, creating it if needed (for an index of a folder of photos, a folder
    of links in ~/Pictures/Photosearch albums). Only adds; never removes or deletes. Check the photos with view_photos
    first."""
    # in its own process, as the page's adds are: AppleScript from this server's worker threads can hang for minutes
    return f"added {photos_app.add_to_photos_album(name, uuids)} of {len(uuids)} photos to album '{name}'"


class ReviewPhoto(TypedDict):
    uuid: str
    caption: str


class Chapter(TypedDict, total=False):
    title: str
    text: str
    photos: list[ReviewPhoto]


@mcp.tool(annotations=READ)
def on_this_day(day: str | None = None) -> list:
    """The best few photos from this date in each earlier year (day: "MM-DD", default today), with the trip each
    was part of, as one numbered contact sheet plus the details. Falls back to the week around the day if the day
    itself has none. Look at the sheet before describing what was happening."""
    r = explore.on_this_day(con, day)
    if not r["years"]:
        return [f"no photos from around {r['day']} in any earlier year"]
    photos = [p for y in r["years"] for p in y["photos"]][:SHEET_MAX]
    sheet = images.contact_sheet(con, [p["uuid"] for p in photos], cell=CELL)
    n, out = 0, []
    for y in r["years"]:
        nums = list(range(n + 1, n + 1 + len(y["photos"]))); n += len(y["photos"])
        out.append(dict(year=y["year"], years_ago=y["ago"], trip=y["trip"], photos=[dict(**({"n": k} if k <= SHEET_MAX else {}), **p)  # past the sheet: no number
                                                                                 for k, p in zip(nums, tidy(y["photos"]))]))
    return [Image(data=sheet, format="jpeg"), json.dumps(dict(day=r["day"], week_around=bool(r["window"]), years=out), ensure_ascii=False)]


@mcp.tool(annotations=READ)
def list_stories() -> list[dict]:
    """The stories: first those of any photos that the user or an agent made (kind "own", ids like
    "story-grandma-at-80"), then the trips (found from where photos were taken) and years, newest first, with their
    ids, days, photo counts, and who made the saved story: none (an automatic one is made when played), "you" (the
    user) or "agent" (with its name, and edited=true if the user changed it since)."""
    return [{k: v for k, v in s.items() if k != "cover" and v is not None} for s in stories.stories(con)]


@mcp.tool(annotations=READ)
def story_highlights(story: str, count: int = 40) -> list:
    """Candidates for a story (a year like "2025", or a trip id from list_stories like "trip-2024-05-02"): a varied
    set of its best photos (near-duplicates removed, spread across events), in date order, as numbered contact
    sheets plus their dates, places and people."""
    h = stories.story_highlights(con, story, min(count, 60))
    if not h:
        return [f"no photos indexed for {story}"]
    out = [Image(data=images.contact_sheet(con, [x["uuid"] for x in h[i:i + SHEET_MAX]], cell=CELL), format="jpeg")
           for i in range(0, len(h), SHEET_MAX)]
    key = [dict(n=n + 1, **{k: v for k, v in x.items() if k in ("uuid", "date", "place", "persons", "event") and v not in ("", [])})
           for n, x in enumerate(h)]
    return out + [json.dumps(key, ensure_ascii=False)]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def save_story(story: str, title: str, intro: str, chapters: list[Chapter], outro: str = "", replace: bool = False,
               ctx: Context | None = None) -> str:
    """Save a story and get the link to its slideshow. `story` is a year ("2025"), a trip id from list_stories, or, for
    a story of any photos from any days (a person over the years, a first year, a birthday book), "story-" and a
    short name in lowercase words with hyphens ("story-grandma-at-80"); its days come from its photos. For a year or
    trip, pick ~20-30 photos from story_highlights, plus any you found with search_photos; for a story of any photos,
    from search_photos, best_per_year and similar_photos (look at them first: skip blurry shots, near-repeats, receipts and too
    many selfies), group them into 4-8 chapters in date order with short titles (for a trip, usually by day or
    place), and give each photo a one-line caption. Captions should describe what's in the photo, using only names
    from the photo's tagged people; don't invent events or feelings. Replaces an earlier automatic or agent's story;
    one the user made or edited only with replace=True, after asking them."""
    uuids = [p["uuid"] for c in chapters for p in c.get("photos", [])]
    own = story.startswith(stories.OWN)
    if own and not stories.STORY_ID.fullmatch(story):
        raise ValueError(f"a story of any photos needs an id like story-grandma-at-80, not {story!r}")
    fields = None if own else stories.story_span(con, story)[2]
    old = stories.saved_review(story)
    if old and (old.get("made_by") == "you" or old.get("edited")) and not replace:
        raise ValueError(f"the user {'made' if old.get('made_by') == 'you' else 'edited'} the story {story!r} "
                         f"(\"{old.get('title')}\"); ask them before replacing it, then call again with replace=true")
    known = store.photo_info(con, uuids)
    bad = [u for u in uuids if u not in known]
    if bad:
        raise ValueError(f"not in the index: {bad}")
    if own:
        fields = stories.own_fields(con, story, uuids)
    stories.save_review(dict(fields, title=title, intro=intro, outro=outro, made_by="agent", agent=agent(ctx), chapters=chapters))
    # full-size copies from iCloud for photos whose local preview is tiny (~1 s each), so the slideshow is sharp
    photos_app.fetch_in_subprocess(con, [p["uuid"] for c in chapters for p in c.get("photos", [])], wait=False)
    n = sum(len(c.get("photos", [])) for c in chapters)
    return (f"saved {n} photos in {len(chapters)} chapters. Slideshow: http://localhost:8765/review/{story} "
            f"(needs `photosearch serve`; also listed under Stories). One-file copy to share: "
            f"`uv run photosearch review {story} --export {story}.html`")


def print_to(folder, name):
    """A path for a new file in folder (default ~/Downloads), "name (2).pdf" if name is taken."""
    d = Path(folder).expanduser() if folder else Path.home() / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    f, n = d / name, 1
    while f.exists():
        n += 1; f = d / f"{Path(name).stem} ({n}){Path(name).suffix}"
    return f


def soft(low):
    """Photos that print soft, worst first, as the agent can find them again: by date and place."""
    info = store.photo_info(con, list(low))
    return [dict(uuid=u, dpi=dpi, date=info[u]["date"], place=info[u]["place"]) for u, dpi in sorted(low.items(), key=lambda x: x[1])]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def make_book(story: str, size: Literal["a4", "letter"] = "a4", bleed: bool = False, folder: str | None = None) -> str:
    """Print a saved story (save_story first) as a photo book: a PDF of 300 dpi landscape pages, a cover, then each
    chapter opening on its title and first photo, the rest two to a page with captions, dates and places. Photos are
    fitted, never cropped. Writes a new file to folder (default ~/Downloads) and returns its path, and the photos
    that would print soft (under 150 dpi). Swap those for sharper look-alikes (similar_photos) and save the story
    again if there are better ones, then make the book again. Fetches full-size copies from iCloud first (~1 s a
    photo)."""
    from . import book
    r = stories.load_review(con, story)
    photos_app.fetch_in_subprocess(con, stories.story_uuids(r))
    data, low = book.book(con, r, size, bleed)
    f = print_to(folder, book.book_name(r))
    f.write_bytes(data)
    return json.dumps(dict(file=str(f), mb=round(len(data) / 1e6, 1), soft=soft(low)), ensure_ascii=False)


class Month(TypedDict, total=False):
    uuid: str
    caption: str


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def make_calendar(year: int, months: list[Month] | None = None, title: str | None = None, photos_from: int | None = None,
                  size: Literal["a4", "letter"] = "a4", bleed: bool = False, folder: str | None = None) -> str:
    """A wall calendar for year, to print: a PDF of 300 dpi portrait pages, a cover, then each month's photo above
    its days (weeks start on Monday on A4, Sunday on Letter). months: twelve {uuid, caption}, January first; pick
    photos that suit each month (snow in January, not in July), mostly landscape, and look at them first. Captions,
    if any, say what's in the photo, with names only from its tagged people. Without months, it picks the best photo
    of each month of photos_from (default: the year before). Writes a new file to folder (default ~/Downloads) and
    returns its path, and the photos that would print soft (under 150 dpi)."""
    from . import book
    months = months or book.month_picks(con, photos_from or year - 1)
    photos_app.fetch_in_subprocess(con, [m["uuid"] for m in months])
    data, low = book.wall_calendar(con, year, months, title, size, bleed)
    f = print_to(folder, f"calendar-{year}.pdf")
    f.write_bytes(data)
    return json.dumps(dict(file=str(f), mb=round(len(data) / 1e6, 1), soft=soft(low)), ensure_ascii=False)


@mcp.tool(annotations=READ)
def eval_sheet(test: str | None = None, n: int | None = None, judge: str | None = None, ctx: Context | None = None) -> list:
    """Judge an experiment (`photosearch eval`) blind. Without a test: the tests and how far each judge has got.
    With one: sheet n, or this judge's next one: the search and two rows, X and Y, of numbered photos from two
    versions of search, in random order. Judge each photo against the search only, then call score_eval_sheet.
    Don't try to work out which row is which version. judge: whose verdicts these are, the agent's own name if left out."""
    judge = judge_name(judge, ctx)
    if not test:
        return [json.dumps(evals.runs())]
    sh = evals.sheet(test, n, judge)
    if sh.get("done"):
        return [json.dumps(dict(sh, next="every sheet is judged; the results are in `photosearch eval report`"))]
    image = (evals.EVALS / test / "sheets" / f"{sh['n']:02d}.jpg").read_bytes()  # rows X and Y, each numbered 1..k
    key = dict(test=test, n=sh["n"], of=sh["total"], left=sh["left"], search=sh["q"], already=sh["verdict"])
    return [Image(data=image, format="jpeg"), json.dumps(key)]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def score_eval_sheet(test: str, n: int, x: list[int], y: list[int], first: Literal["x", "y", "same"],
                     judge: str | None = None, ctx: Context | None = None) -> str:
    """Record a verdict on sheet n of a test: the numbers (1..k within each row) of the photos in row X and in row Y
    that fit the search, and whose first photo fits it better. Kept under the judge's name; scoring a sheet again replaces it."""
    left = evals.record(test, n, judge_name(judge, ctx), x, y, first)
    return f"saved; {left} sheets left" if left else "saved; every sheet is judged"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
