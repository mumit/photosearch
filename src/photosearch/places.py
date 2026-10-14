"""Where photos were taken: home, trips, the map."""
import json, math
from collections import Counter, defaultdict
from datetime import date

from .store import DATED, photo_info, vectors
from .search import interest

AWAY_KM = 75   # the next city over, ~95 km away, is a trip
TRIP_MIN = 20  # photos; fewer is a stopover or a ferry ride


def short_place(place):
    return (place or "").split(",")[0]


def km(a, b):
    """Great-circle distance between two (lat, lon) points."""
    la, lb, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    return 6371 * math.acos(min(1.0, math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(dl)))


def trip_name(geos):
    """ "Minneapolis & Saint Paul"; the wider area when no one city dominates ("Lisbon", not its boroughs)."""
    geos = [g for g in geos if g]
    top = lambda k: Counter(g[k] for g in geos if k in g).most_common(2)
    city, half = top("city"), len(geos) / 2
    if city and city[0][1] >= half:
        return " & ".join(c for c, n in city if n >= len(geos) / 5)
    for t in (top("water"), top("area"), top("state"), top("country")):
        if t and t[0][1] >= half:
            return t[0][0]
    return " & ".join(c for c, _ in city) or "Trip"


def homes(rows):
    """Home for each year: the ~10 km cell with the most days photographed within 30 km of it. Counting days, not
    photos, and pooling nearby cells keeps a busy week away from outvoting a home spread across several cells."""
    days = defaultdict(lambda: defaultdict(set))
    for d, la, lo, *_ in rows:
        if la is not None:
            days[d[:4]][round(la, 1), round(lo, 1)].add(d[:10])
    def best(cells):
        return max(cells, key=lambda c: len(set().union(*(v for o, v in cells.items() if km(c, o) <= 30))))
    return {y: best(cells) for y, cells in days.items()}


def trips(con):
    """Runs of days spent mostly AWAY_KM+ from home, newest first. Home is worked out per year, so moving house
    doesn't make the new home a trip. A day without location in the middle stays inside the trip; a day
    photographed at home ends it."""
    rows = con.execute(f"select date, lat, lon, geo from photos where {DATED} order by date").fetchall()
    home = homes(rows)
    days = {}
    for d, la, lo, g in rows:
        e = days.setdefault(d[:10], dict(n=0, away=0, home=0, geo=[]))
        e["n"] += 1
        if la is not None and km(home[d[:4]], (la, lo)) > AWAY_KM:
            e["away"] += 1; e["geo"].append(json.loads(g or "{}"))
        elif la is not None:
            e["home"] += 1
    out, cur = [], None
    for d, e in days.items():
        if e["away"] > e["home"]:
            if cur and (date.fromisoformat(d) - date.fromisoformat(cur["end"])).days <= 2:
                cur["end"] = d
            else:
                cur = dict(start=d, end=d, geo=[]); out.append(cur)
            cur["geo"] += e["geo"]
        elif e["home"]:
            cur = None
    for t in out:
        t["photos"] = sum(e["n"] for d, e in days.items() if t["start"] <= d <= t["end"])
        t.update(id=f"trip-{t['start']}", name=trip_name(t.pop("geo")))
    return [t for t in out if t["photos"] >= TRIP_MIN][::-1]


def find_trip(con, rid):
    t = next((t for t in trips(con) if t["id"] == rid), None)
    if not t:
        raise LookupError(f"no trip starting {rid.removeprefix('trip-')} (see `photosearch trips`)")
    return t


def world(con):
    """Where the photos were taken, in ~1 km cells (position, count, the most interesting photo, the place's name), and
    the regions they make: cells within ~80 km of the busiest one, named like trips are ("Lisbon")."""
    uuids, _, pos = vectors(con)
    score = interest(con)
    cells = {}
    for u, la, lo, place, d, g in con.execute("select uuid, lat, lon, place, substr(date,1,10), geo from photos where lat is not null and lon is not null"):
        if u not in pos:
            continue
        c = cells.setdefault((round(la, 2), round(lo, 2)), dict(lat=0.0, lon=0.0, n=0, best=-9, cover=None, names=Counter(), geos=[], first=d, last=d))
        if len(c["geos"]) < 50:
            c["geos"].append(json.loads(g or "{}"))
        c["lat"] += la; c["lon"] += lo; c["n"] += 1
        if place:
            c["names"][short_place(place)] += 1
        c["first"], c["last"] = min(c["first"], d), max(c["last"], d)
        if score[pos[u]] > c["best"]:
            c.update(best=float(score[pos[u]]), cover=u)
    out = [dict(lat=round(c["lat"] / c["n"], 5), lon=round(c["lon"] / c["n"], 5), n=c["n"], cover=c["cover"],
                place=c["names"].most_common(1)[0][0] if c["names"] else "", first=c["first"], last=c["last"]) for c in cells.values()]
    regions = []
    for k in sorted(range(len(out)), key=lambda k: -out[k]["n"]):
        c = out[k]
        r = next((r for r in regions if km((r["lat"], r["lon"]), (c["lat"], c["lon"])) < 80), None)
        if r is None:
            r = dict(lat=c["lat"], lon=c["lon"], n=0, cells=[], geos=[]); regions.append(r)
        r["n"] += c["n"]; r["cells"].append(k); r["geos"] += list(cells.values())[k]["geos"]
    for r in regions:
        ks = r["cells"]
        r.update(name=trip_name(r.pop("geos")), bounds=[min(out[k]["lat"] for k in ks), min(out[k]["lon"] for k in ks),
                                                       max(out[k]["lat"] for k in ks), max(out[k]["lon"] for k in ks)])
    return dict(cells=out, regions=regions)


def near(con, lat, lon, radius_km=2.0, k=60):
    """The most interesting photos taken within radius_km of a point, best first."""
    dlat = radius_km / 111; dlon = radius_km / (111 * max(0.1, math.cos(math.radians(lat))))
    rows = con.execute("select uuid, lat, lon from photos where lat between ? and ? and lon between ? and ?",
                       (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
    _, _, pos = vectors(con)
    score = interest(con)
    keep = [u for u, la, lo in rows if u in pos and km((lat, lon), (la, lo)) <= radius_km]
    top = sorted(keep, key=lambda u: -score[pos[u]])[:k]
    info = photo_info(con, top)
    return dict(n=len(keep), photos=[info[u] for u in top])
