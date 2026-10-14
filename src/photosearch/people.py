"""The people tagged in Photos: who, their best portrait, their page."""
import json
from collections import Counter, defaultdict

from . import embed
from .store import DATED, photo_info, vectors
from .search import MIN_INTEREST, interest
from .places import short_place

PORTRAIT = "a close-up portrait photo of a person's smiling face"

def portraits(con, rows):
    """rows: (uuid, year, number of other people). The best portrait among them: a close-up of a face (the search model
    can tell), from the last three years they were photographed (kids change), preferably of them alone."""
    _, M, pos = vectors(con)
    score = interest(con)
    rows = [r for r in rows if r[0] in pos and score[pos[r[0]]] >= MIN_INTEREST] or rows  # not an ID card or a screenshot
    last = max(r[1] for r in rows)
    cand = [r for r in rows if r[1] >= last - 2 and r[0] in pos]
    q = embed.embed_query(PORTRAIT)
    return max(cand, key=lambda r: float(M[pos[r[0]]] @ q) - 0.02 * min(r[2], 4))[0]


def people(con, n=30):
    """The most photographed people, each with a portrait, for the home page."""
    _, _, pos = vectors(con)
    count, rows = Counter(), defaultdict(list)
    for u, ps, kind, y in con.execute(f"select uuid, persons, kind, cast(substr(date,1,4) as int) from photos where persons != '[]' and {DATED}"):
        if u not in pos:
            continue
        names = json.loads(ps)
        count.update(names)
        if kind == "photo":
            for name in names:
                rows[name].append((u, y, len(names) - 1))
    return [dict(name=p, n=c, cover=portraits(con, rows[p]) if rows[p] else None) for p, c in count.most_common(n)]


def person(con, name):
    """One person's page: their best photo each year, who they're photographed with, and where."""
    uuids, _, pos = vectors(con)
    score = interest(con)
    rows = [r for r in con.execute(f"select uuid, substr(date,1,10), persons, place, kind from photos where {DATED} and "
                                   "exists (select 1 from json_each(persons) where value = ?)", (name,)) if r[0] in pos]
    if not rows:
        raise LookupError(f"nobody called {name!r} is tagged")
    by_year, with_, places, faces = {}, Counter(), Counter(), []
    for u, d, ps, place, kind in rows:
        others = [p for p in json.loads(ps) if p != name]
        with_.update(others)
        if place:
            places[short_place(place)] += 1
        s_ = score[pos[u]] - 0.03 * len(others)
        if kind == "photo":
            faces.append((u, int(d[:4]), len(others)))
        if kind == "photo" and s_ > by_year.get(d[:4], (-9, None))[0]:
            by_year[d[:4]] = (s_, u)
    info = photo_info(con, [u for _, u in by_year.values()])
    dates = sorted(r[1] for r in rows)
    return dict(name=name, n=len(rows), first=dates[0], last=dates[-1], portrait=portraits(con, faces) if faces else None,
                years=[dict(info[u], year=int(y)) for y, (_, u) in sorted(by_year.items())],
                together=with_.most_common(8), places=places.most_common(8))
