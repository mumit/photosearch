"""photosearch: semantic search over an Apple Photos library with EmbeddingGemma 2.

  photosearch index [--limit N] [--library PATH]        embed photos (incremental; safe to re-run)
  photosearch search "kids on a slide" [-k 24] [--person NAME] [--after 2020-01-01] [--before ...]
  photosearch similar UUID [-k 24]                      photos that look like this one
  photosearch serve [--port 8765] [--lan]               the web page: search, map, galaxy, time machine, games, albums
  photosearch album "Name" "query" [-k 50]              put the results into a Photos album
  photosearch today [--day 08-14]                       photos from this day in earlier years
  photosearch trips                                     trips, found from where photos were taken
  photosearch review 2025|trip-2024-05-02 [--export F.html]   a year or a trip as a slideshow

Nothing is downloaded from iCloud: with "Optimize Mac Storage" on we embed the
local preview Photos keeps (the model only sees ~280 visual tokens anyway).
"""
import argparse, json, sys
from pathlib import Path

from . import embed
from .store import db, photos_db
from .index import cmd_index, cmd_thumbs
from .search import search, similar
from .places import trips
from .explore import on_this_day
from .stories import REVIEWS, auto_review, date_range, load_review, render_review, save_review, story_uuids
from .photos_app import cmd_add_to_album, cmd_fetch, fetch_large, needs_fetch
from .server import cmd_serve


def cmd_album(a):
    from osxphotos.photosalbum import PhotosAlbum
    res = search(db(), a.query, a.k, **fkw(a))
    order = {r["uuid"]: i for i, r in enumerate(res)}
    photos = sorted(photos_db().photos(uuid=list(order)), key=lambda p: order[p.uuid])
    PhotosAlbum(a.name).add_list(photos)
    print(f"added {len(photos)} photos to album '{a.name}'")


def show(results):
    for r in results:
        who = ", ".join(r["persons"])
        print(f"{r['score']:.3f}  {r['date']}  {r['kind']:5}  {r['uuid']}  {r['place'][:40]}  {who}")


def fkw(a):
    return dict(person=a.person, after=a.after, before=a.before, kind=a.kind, place=a.place)


def cmd_search(a): show(search(db(), a.query, a.k, a.exclude, **fkw(a)))
def cmd_similar(a): show(similar(db(), a.uuid, a.k, **fkw(a)))


def cmd_trips(a):
    con = db()
    made = {f.stem: json.loads(f.read_text()).get("made_by") for f in REVIEWS.glob("*.json")} if REVIEWS.exists() else {}
    for t in trips(con):
        tag = {"claude": "  ✨ curated", "auto": "  (automatic review)"}.get(made.get(t["id"]), "")
        print(f"{t['id']}  {date_range(t['start'], t['end']):30}  {t['photos']:5} photos  {t['name']}{tag}")


def cmd_review(a):
    con = db()
    if a.auto:
        save_review(auto_review(con, a.story))
    r = load_review(con, a.story, make=True)
    print(f"{r['title']}: {sum(len(c['photos']) for c in r['chapters'])} photos in {len(r['chapters'])} chapters "
          f"(made by {r['made_by']})")
    if a.export:
        if need := [u for u in story_uuids(r) if needs_fetch(con, u)]:
            print(f"fetching full-size copies of {len(need)} photos from iCloud…")
            fetch_large(con, need, log=print)
        Path(a.export).write_text(render_review(con, r, embed=True))
        print(f"wrote {a.export} ({Path(a.export).stat().st_size / 1e6:.1f} MB): one file, opens in any browser")


def cmd_today(a):
    r = on_this_day(db(), a.day)
    if r["window"]:
        print(f"nothing on {r['day']} itself; the week around it:")
    for y in r["years"]:
        trip = f"  (trip: {y['trip']['name']}, {y['trip']['id']})" if y["trip"] else ""
        ago = "this year" if not y["ago"] else f"{y['ago']} year{'s' * (y['ago'] > 1)} ago"
        print(f"\n{y['year']} · {ago}{trip}")
        show([dict(x, score=0.0) for x in y["photos"]])


def main():
    ap = argparse.ArgumentParser(prog="photosearch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("-k", type=int, default=24)
        p.add_argument("--person"); p.add_argument("--after"); p.add_argument("--before"); p.add_argument("--place")
        p.add_argument("--kind", choices=["photo", "video"])

    p = sub.add_parser("index"); p.add_argument("--limit", type=int); p.add_argument("--library")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--vision-tokens", type=int, default=embed.VISION_TOKENS,
                   help="per-image token budget; keep it the same for the whole index"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--exclude", help='e.g. "a selfie"')
    filters(p); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("similar"); p.add_argument("uuid"); filters(p); p.set_defaults(fn=cmd_similar)
    p = sub.add_parser("album"); p.add_argument("name"); p.add_argument("query"); filters(p); p.set_defaults(fn=cmd_album)
    p = sub.add_parser("add-to-album", help="add photos (by uuid) to an album in Photos; used by the web page")
    p.add_argument("name"); p.add_argument("uuids", nargs="+"); p.set_defaults(fn=cmd_add_to_album)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--lan", action="store_true", help="also let phones and tablets on this network in, with a passcode")
    p.add_argument("--new-passcode", action="store_true", help="with --lan: a new passcode, and every device signs in again")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("fetch", help="full-size copies from iCloud for photos whose local preview is small")
    p.add_argument("what", nargs="+", help="story ids (2025, trip-2024-05-02) or photo uuids"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("thumbs", help="rebuild thumbnails at the current size, where the source allows")
    p.set_defaults(fn=cmd_thumbs)
    p = sub.add_parser("today", help="photos from this day in earlier years")
    p.add_argument("--day", help="MM-DD instead of today"); p.set_defaults(fn=cmd_today)
    p = sub.add_parser("trips", help="trips, found from where photos were taken"); p.set_defaults(fn=cmd_trips)
    p = sub.add_parser("review", help="a year or trip as a slideshow: build (if needed), optionally export as one file")
    p.add_argument("story", help="a year (2025) or a trip id from `photosearch trips` (trip-2024-05-02)")
    p.add_argument("--auto", action="store_true", help="rebuild the automatic version")
    p.add_argument("--export", metavar="FILE.html"); p.set_defaults(fn=cmd_review)
    a = ap.parse_args()
    if getattr(a, "vision_tokens", None):
        embed.VISION_TOKENS = a.vision_tokens
    try:
        a.fn(a)
    except LookupError as ex:
        sys.exit(str(ex))
