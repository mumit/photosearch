"""Stories: a year or a trip as a slideshow, made automatically, by Claude, or edited by hand."""
import json, re, unicodedata
from collections import Counter
from datetime import date, datetime, timedelta

import numpy as np

from .config import DATA, WEB
from .store import DATED, photo_info, vectors
from .images import photo_jpeg
from .search import MIN_INTEREST, interest, search, similar
from .places import AWAY_KM, find_trip, homes, km, short_place, trips

REVIEWS = DATA / "reviews"
MONTHS = "January February March April May June July August September October November December".split()
STORY_ID = re.compile(r"\d{4}|trip-\d{4}-\d{2}-\d{2}")  # "2025", or a trip by its first day


def day_after(d):
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def date_range(start, end):
    """ "August 10–18, 2026" """
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    ma, mb = MONTHS[a.month - 1], MONTHS[b.month - 1]
    if a == b:
        return f"{ma} {a.day}, {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{ma} {a.day}–{b.day}, {a.year}"
    if a.year == b.year:
        return f"{ma} {a.day} – {mb} {b.day}, {a.year}"
    return f"{ma} {a.day}, {a.year} – {mb} {b.day}, {b.year}"


def span_photos(con, start, end, home=None, exact=False):
    """(uuid, date, persons) of the indexed photos from day start to day end (inclusive), in time order. home: a
    (lat, lon) whose photos to leave out, e.g. a trip's first morning at home; photos without a location stay.
    exact: leave out photos the date detective dated only to a month or a year."""
    _, _, pos = vectors(con)
    guessed = " and uuid not in (select uuid from redated where precision != 'day')" if exact else ""
    return [r[:3] for r in con.execute(f"select uuid, date, persons, lat, lon from photos where kind='photo' and date >= ? "
                                       f"and date < ? and {DATED}{guessed} order by date", (start, day_after(end)))
            if r[0] in pos and not (home and r[3] is not None and km(home, (r[3], r[4])) <= AWAY_KM)]


def highlights(con, start, end, n=40, home=None, exact=False):
    """A varied set of the best photos taken from day start to day end (inclusive), in date order: candidates for a
    review (home as in span_photos). Greedy pick of the most interesting photo (family photos count a little extra),
    skipping near-duplicates of anything already picked and spreading picks across events (runs of photos with no
    day-long gap)."""
    uuids, M, pos = vectors(con)
    rows = span_photos(con, start, end, home, exact)
    if not rows:
        return []
    times = [datetime.fromisoformat(r[1]) for r in rows]
    event = np.cumsum([0] + [(b - a).total_seconds() > 86400 for a, b in zip(times, times[1:])])
    V = M[[pos[r[0]] for r in rows]]
    score = interest(con)[[pos[r[0]] for r in rows]]
    base = score + 0.02 * np.array([min(len(json.loads(r[2])), 3) for r in rows])
    base[score < MIN_INTEREST] = -np.inf
    picked, per_event, closest = [], np.zeros(event[-1] + 1), np.full(len(rows), -1.0)
    for _ in range(min(n, len(rows))):
        val = base - 0.3 * np.clip(closest, 0, None) - 0.04 * per_event[event]
        val[closest > 0.9] = -np.inf  # near-duplicates of a pick (and the picks themselves)
        i = int(np.argmax(val))
        if val[i] == -np.inf:
            break
        picked.append(i); per_event[event[i]] += 1
        closest = np.maximum(closest, V @ V[i])
    info = photo_info(con, [rows[i][0] for i in picked])
    return [dict(info[rows[i][0]], event=int(event[i]), interest=round(float(score[i]), 3)) for i in sorted(picked)]


def cover(con, start, end):
    """The most interesting photo between two days, for a story's card."""
    uuids, M, pos = vectors(con)
    rows = [r[0] for r in con.execute(f"select uuid from photos where kind='photo' and date >= ? and date < ? and {DATED}",
                                      (start, day_after(end))) if r[0] in pos]
    score = interest(con)
    return max(rows, key=lambda u: score[pos[u]]) if rows else None


def story_span(con, rid):
    """(first day, last day, fields every review of it carries) for a year or a trip. A trip with a review you or
    Claude made keeps the days it was made with, even if new photos would now shift where the trip is detected."""
    if not STORY_ID.fullmatch(rid):
        raise LookupError(f"not a story id: {rid!r} (a year like 2025, or a trip like trip-2024-05-02)")
    if rid.isdigit():
        return f"{rid}-01-01", f"{rid}-12-31", dict(id=rid, kind="year", year=int(rid))
    t = saved_review(rid) or find_trip(con, rid)
    return t["start"], t["end"], dict(id=rid, kind="trip", start=t["start"], end=t["end"])


def story_home(con, fields):
    """Home in the year a trip started, so its highlights can skip photos taken there; None for a year."""
    if fields["kind"] != "trip":
        return None
    return homes(con.execute("select date, lat, lon from photos where substr(date,1,4) = ?", (fields["start"][:4],)).fetchall()).get(fields["start"][:4])


def story_highlights(con, rid, n=40):
    start, end, fields = story_span(con, rid)
    return highlights(con, start, end, n, story_home(con, fields))


def auto_review(con, rid, n=30):
    """A review without Claude: highlights grouped by month (a year) or by day (a trip), captioned with who's in them.
    The place and date show under every photo already, so the caption is just the names."""
    start, end, fields = story_span(con, rid)
    trip = fields["kind"] == "trip"
    chapters = []
    for h in story_highlights(con, rid, min(n, max(12, find_trip(con, rid)["photos"] // 10)) if trip else n):
        key = h["date"] if trip else MONTHS[int(h["date"][5:7]) - 1]
        if not chapters or chapters[-1]["key"] != key:
            chapters.append(dict(key=key, photos=[], places=Counter()))
        chapters[-1]["photos"].append(dict(uuid=h["uuid"], caption=" & ".join(p.split()[0] for p in h["persons"][:3])))
        chapters[-1]["places"][short_place(h["place"])] += bool(h["place"])
    for c in chapters:
        key, places = c.pop("key"), c.pop("places")
        if trip:  # "Day 3 · Sintra"
            place = [p for p, k in places.most_common(1) if k]
            key = f"Day {(date.fromisoformat(key) - date.fromisoformat(start)).days + 1}" + "".join(f" · {p}" for p in place)
        c["title"] = key
    n = sum(len(c["photos"]) for c in chapters)
    title = find_trip(con, rid)["name"] if trip else rid
    intro = f"{date_range(start, end)} · {n} moments" if trip else f"{n} moments from {rid}"
    return dict(fields, title=title, intro=intro, made_by="auto", chapters=chapters)


def save_review(review):
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"{review['id']}.json").write_text(json.dumps(review, indent=1, ensure_ascii=False))


def saved_review(rid):
    """The review saved for a story, or None. Automatic ones don't count: they're made afresh each time, so they follow
    the library (new photos, deleted ones, places Photos has named since). Yours and Claude's are kept as made."""
    f = REVIEWS / f"{rid}.json"
    r = json.loads(f.read_text()) if f.exists() else None
    return r if r and r.get("made_by") != "auto" else None


def load_review(con, rid, make=False):
    r = saved_review(rid)
    if r:
        return dict(r, id=rid, kind=r.get("kind", "year"))  # year reviews saved before trips existed
    if not make and not (REVIEWS / f"{rid}.json").exists():
        raise LookupError(f"no review for {rid}")
    r = auto_review(con, rid)
    save_review(r)
    return r


def stories(con):
    """Every trip and year, newest first: its saved review's title and author if it has one, else what was detected."""
    made = {f.stem: r for f in REVIEWS.glob("*.json") if (r := saved_review(f.stem))} if REVIEWS.exists() else {}
    def story(rid, start, end, **x):
        r = made.get(rid, {})
        first = next((p["uuid"] for c in r.get("chapters", []) for p in c["photos"]), None)
        return dict(x, id=rid, start=start, end=end, title=r.get("title", x.get("title")), made_by=r.get("made_by"), edited=r.get("edited"),
                    cover=first or cover(con, start, end))
    found = {t["id"]: t for t in trips(con)}
    for rid, r in made.items():  # a saved trip that new photos have since merged into another, or moved
        if r.get("kind") == "trip" and rid not in found:
            n = con.execute("select count(*) from photos where date >= ? and date < ?", (r["start"], day_after(r["end"])))
            found[rid] = dict(r, photos=n.fetchone()[0], name=r["title"])
    out = [story(t["id"], t["start"], t["end"], kind="trip", title=t["name"], photos=t["photos"])
           for t in sorted(found.values(), key=lambda t: t["start"], reverse=True)]
    years = con.execute(f"select substr(date,1,4) y, count(*) from photos where {DATED} group by y order by y desc")
    return out + [story(y, f"{y}-01-01", f"{y}-12-31", kind="year", title=y, photos=n) for y, n in years.fetchall()]


def story_photos(con, uuids):
    """photo_info plus the full timestamp (photo_info keeps just the day), so the editor can slot photos in by time."""
    if not uuids:
        return {}
    info = photo_info(con, uuids)
    for u, t in con.execute(f"select uuid, date from photos where uuid in ({','.join('?' * len(uuids))})", list(uuids)):
        info[u]["taken"] = t
    return info


def story_for_editor(con, rid):
    r = load_review(con, rid, make=True)
    info = story_photos(con, [p["uuid"] for c in r["chapters"] for p in c["photos"]])
    return dict(r, chapters=[dict(c, photos=[dict(info[p["uuid"]], caption=p.get("caption", ""))
                                             for p in c["photos"] if p["uuid"] in info]) for c in r["chapters"]])


def story_candidates(con, rid, q=None, like=None, k=48):
    """Photos from a story's days to add or swap in: matches for q, look-alikes of like, else its highlights, topped
    up with the rest of its photos in time order when there are few (a short trip has only a handful of highlights)."""
    start, end, fields = story_span(con, rid)
    f = dict(after=start, before=day_after(end), kind="photo")
    if q or like:
        res = search(con, q, k, **f) if q else similar(con, like, k, **f)
    else:
        home = story_home(con, fields)
        res = highlights(con, start, end, k, home)
        have = {r["uuid"] for r in res}
        res += [dict(uuid=r[0]) for r in span_photos(con, start, end, home) if r[0] not in have][:k - len(res)]
    info = story_photos(con, [r["uuid"] for r in res])
    return [info[r["uuid"]] for r in res if r["uuid"] in info]


def edit_review(con, body):
    """Save a story edited in the web page. Its author becomes "you" if it was automatic; Claude's stays Claude's,
    marked edited."""
    rid = str(body.get("id", ""))
    _, _, fields = story_span(con, rid)
    old = load_review(con, rid, make=True)
    text = lambda v, n: str(v or "").strip()[:n]
    chapters = [dict(title=text(c.get("title"), 120) or "Untitled", text=text(c.get("text"), 500),
                     photos=[dict(uuid=text(x.get("uuid"), 64), caption=text(x.get("caption"), 300)) for x in c.get("photos", [])])
                for c in body.get("chapters", [])]
    uuids = [x["uuid"] for c in chapters for x in c["photos"]]
    bad = set(uuids) - photo_info(con, uuids).keys() if uuids else set()
    if bad:
        raise ValueError(f"not in the index: {sorted(bad)}")
    made_by = "you" if old["made_by"] == "auto" else old["made_by"]
    save_review(dict(fields, title=text(body.get("title"), 120) or old["title"], intro=text(body.get("intro"), 300),
                     outro=text(body.get("outro"), 300), made_by=made_by, **({"edited": True} if made_by == "claude" else {}),
                     chapters=chapters))
    return dict(photos=len(uuids), chapters=len(chapters), made_by=made_by)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).strip("-")


def export_name(review):
    if review["kind"] == "year":
        return f"year-in-review-{review['id']}.html"
    return f"{slug(review['title']) or 'trip'}-{review['start'][:4]}.html"


def render_review(con, review, embed=False):
    """The slideshow page for a review. embed=True inlines every photo, making one file you can send to family."""
    import base64
    info = photo_info(con, [p["uuid"] for c in review["chapters"] for p in c["photos"]])
    def src(u):
        # 1600 px: sharp on a laptop or TV, and a 27-photo story is ~13 MB, under email attachment limits
        return "data:image/jpeg;base64," + base64.b64encode(photo_jpeg(con, u, 1600, 80)).decode() if embed else f"/photo/{u}.jpg"
    kicker = date_range(review["start"], review["end"]) if review.get("kind") == "trip" else "Year in review"
    data = dict(review, kicker=kicker,
                chapters=[dict(title=c["title"], text=c.get("text", ""),
                               photos=[dict(src=src(p["uuid"]), caption=p.get("caption", ""),
                                            date=info[p["uuid"]]["date"], place=short_place(info[p["uuid"]]["place"]))
                                       for p in c["photos"] if p["uuid"] in info])
                          for c in review["chapters"]])
    page = (WEB / "review.html").read_text()
    return page.replace("/*REVIEW*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def story_uuids(review):
    return [p["uuid"] for c in review["chapters"] for p in c["photos"]]
