"""The playful views: galaxy, time machine, rediscover, the calendar, games, photo math, on this day."""
import calendar, json, random, re
from collections import Counter
from datetime import date, timedelta

import numpy as np

from . import embed
from .config import DATA
from .store import DATED, photo_info, vec_of, vectors
from .search import interest, rank
from .places import short_place, trips
from .stories import highlights


def galaxy(con):
    """2-D map of the library (UMAP over the vectors) with named regions. Cached; redone once the index grows 10%, and
    as soon as any photo in it has left the library (it mustn't keep showing what was deleted)."""
    uuids, M, _ = vectors(con)
    f = DATA / "galaxy.json"
    if f.exists():
        g = json.loads(f.read_text())
        if len(g["uuids"]) >= 0.9 * len(uuids) and set(g["uuids"]) <= set(uuids):
            return g
    import umap
    from sklearn.cluster import KMeans
    # a high min_dist spreads near-duplicates out, so zooming in shows photos rather than empty space and clumps
    xy = umap.UMAP(n_neighbors=15, min_dist=0.6, spread=1.5, metric="cosine").fit_transform(M)
    lo, hi = np.percentile(xy, 2, 0), np.percentile(xy, 98, 0)  # strays get pinned to the edge
    xy = np.clip((xy - lo) / (hi - lo), 0, 1)
    k = max(2, min(48, len(uuids) // 150))
    cl = KMeans(k, n_init=4, random_state=0).fit_predict(M)
    rows = {r[0]: r[1:] for r in con.execute(f"select uuid, iif({DATED}, substr(date,1,4), 0), labels from photos")}
    docs = [set(json.loads(rows[u][1] or "[]")) for u in uuids]
    df = Counter(l for d in docs for l in d)
    regions = []
    for c in range(k):
        idx = np.where(cl == c)[0]
        tf = Counter(l for i in idx for l in docs[i])
        # Apple's labels that are common in this cluster but rare elsewhere
        top = sorted((l for l in tf if tf[l] >= 0.25 * len(idx)),
                     key=lambda l: -tf[l] / len(idx) * np.log(len(docs) / df[l]))[:2]
        cx, cy = np.median(xy[idx], 0)
        regions.append(dict(name=" · ".join(top), x=round(float(cx), 4), y=round(float(cy), 4), n=len(idx)))
    g = dict(uuids=uuids, x=np.round(xy[:, 0], 4).tolist(), y=np.round(xy[:, 1], 4).tolist(),
             year=[int(rows[u][0]) for u in uuids], regions=regions)
    f.write_text(json.dumps(g))
    return g


def timeline(con, query, per=1, person=None):
    """The best match for `query` in each year; with a person, only photos of them (and no query: their best)."""
    uuids, M, pos = vectors(con)
    s = M @ embed.embed_query(query) if query else interest(con).copy()
    years = dict(con.execute(f"select uuid, substr(date,1,4) from photos where {DATED}"))
    if person:
        theirs = {u for (u,) in con.execute("select uuid from photos where exists (select 1 from json_each(persons) where value = ?)", (person,))}
        years = {u: y for u, y in years.items() if u in theirs}
    best = {}
    for i in np.argsort(-s):
        y = years.get(uuids[i])
        if y and len(best.setdefault(y, [])) < per:
            best[y].append(i)
    info = photo_info(con, [uuids[i] for v in best.values() for i in v])
    return [dict(year=int(y), results=[dict(info[uuids[i]], score=float(s[i])) for i in best[y]]) for y in sorted(best)]


def rediscover(con, n=24):
    """A random handful of the library's more interesting photos, for the home page to resurface."""
    uuids, _, _ = vectors(con)
    score = interest(con)
    ok = {r[0] for r in con.execute(f"select uuid from photos where kind='photo' and {DATED}")}
    cand = [uuids[i] for i in np.argsort(-score)[: max(n, len(uuids) * 2 // 5)] if uuids[i] in ok]
    pick = random.sample(cand, min(n, len(cand)))
    info = photo_info(con, pick)
    return [info[u] for u in pick]


def overview(con):
    """Names, places and years, for the search box to suggest as you type."""
    rows = con.execute(f"select persons, place, iif({DATED}, substr(date,1,4), null) from photos").fetchall()
    people = Counter(p for r in rows for p in json.loads(r[0]))
    places = Counter(short_place(r[1]) for r in rows if r[1])
    years = Counter(r[2] for r in rows if r[2])
    return dict(people=people.most_common(80), places=places.most_common(120), years=sorted(years.items()))


def days(con, year):
    """Every day of a year that has photos: how many, and the most interesting one, for a calendar heatmap."""
    uuids, _, pos = vectors(con)
    score = interest(con)
    out = {}
    for u, d in con.execute(f"select uuid, substr(date,1,10) from photos where substr(date,1,4) = ? and {DATED}", (str(year),)):
        if u not in pos:
            continue
        c = out.setdefault(d, [0, -9, None])
        c[0] += 1
        if score[pos[u]] > c[1]:
            c[1], c[2] = float(score[pos[u]]), u
    return dict(year=int(year), days=[dict(d=d, n=c[0], cover=c[2]) for d, c in sorted(out.items())])


def game_round(con, mode="year"):
    """A random, reasonably interesting photo to guess the year or place of."""
    uuids, M, _ = vectors(con)
    score = interest(con)
    where = "kind='photo'" + (" and lat is not null" if mode == "place" else f" and {DATED}")
    ok = {r[0] for r in con.execute(f"select uuid from photos where {where}")}
    cand = [i for i in np.argsort(-score)[: max(20, len(uuids) * 2 // 5)] if uuids[i] in ok]
    if not cand:
        raise LookupError("no photos to play with yet")
    u = uuids[random.choice(cand)]
    years = con.execute(f"select min(substr(date,1,4)), max(substr(date,1,4)) from photos where {DATED}").fetchone()
    return dict(photo_info(con, [u])[u], first=int(years[0]), last=int(years[1]))


def photo_math(con, base, plus="", minus="", w=1.0, k=24):
    """base (a photo uuid, or text) + w * (plus - minus), e.g. this photo + "snow" - "summer"."""
    try:
        v, skip = vec_of(con, base), base
    except LookupError:
        v, skip = embed.embed_query(base), None
    d = (embed.embed_query(plus) if plus else 0) - (embed.embed_query(minus) if minus else 0)
    q = v + w * d
    return [r for r in rank(con, (q / np.linalg.norm(q)).astype(np.float32), k + 1) if r["uuid"] != skip][:k]


def on_this_day(con, day=None, per_year=4):
    """The best few photos from this date (MM-DD, default today) in each earlier year, newest first, each with the
    trip it was part of, if any. If no year has photos on the day itself, it's the week around it instead."""
    today = date.today()
    day = day or today.strftime("%m-%d")
    try:
        m, d = map(int, re.fullmatch(r"(\d{2})-(\d{2})", day).groups())
        date(2000, m, d)  # a leap year, so 02-29 is a day
    except (AttributeError, ValueError):
        raise LookupError(f"not a day: {day!r} (MM-DD, e.g. 08-14)")
    years = [int(y) for (y,) in con.execute(f"select distinct substr(date,1,4) from photos where {DATED} order by 1 desc")]
    found = trips(con)
    for window in (0, 3):
        out = []
        for y in years:
            center = date(y, m, min(d, 28) if (m, d) == (2, 29) and not calendar.isleap(y) else d)
            if center >= today:
                continue
            a, b = (center - timedelta(days=window)).isoformat(), (center + timedelta(days=window)).isoformat()
            picks = highlights(con, a, b, per_year)
            if picks:
                t = next((t for t in found if t["start"] <= center.isoformat() <= t["end"]), None)
                out.append(dict(year=y, ago=today.year - y, date=center.isoformat(), photos=picks,
                                trip=t and {k: t[k] for k in ("id", "name", "start", "end")}))
        if out:
            break
    return dict(day=f"{m:02}-{d:02}", window=window, years=out)
