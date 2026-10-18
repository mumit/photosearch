"""Then and now: two photos from the same spot, years apart, that look alike (the same lookout, the pool in the snow).

A pair is two photos within NEAR_M of each other by GPS, at least YEARS apart, as alike as LOOK_AT. Set by eye on
a 16,000-photo library, from sheets of the best pairs:
- Matching by look alone, without GPS on the older photo, found different places that look alike (Angkor Wat and
  Teotihuacan, two aquariums), so both photos need GPS. Here that means 2016 on.
- Above 0.97 they're copies of one photo; below LOOK_AT, two photos that merely share a park.
- Clutter (an ID shot twice, floors, price tags) and repeat outings (the same two days, a week either side) are left
  out, and a spot gives at most PER_SPOT pairs, so home doesn't fill the list.
"""
import numpy as np

from .clutter import found as clutter_found
from .store import DATED, photo_info, vectors

NEAR_M = 150
YEARS = 4
LOOK_AT, COPY_AT = 0.80, 0.97
SAME_OUTING = 7  # days
PER_SPOT = 3  # pairs per ~1 km
_pairs = (None, None)


def _days(d):
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return y * 372 + m * 31 + dd


def pairs(con):
    """[(score, then, now)], best first."""
    global _pairs
    uuids, M, pos = vectors(con)
    if _pairs[0] is M:
        return _pairs[1]
    junk = {u for v in clutter_found(con).values() for u in v}
    rows = [r for r in con.execute(f"select uuid, date, lat, lon from photos where kind='photo' and lat is not null and {DATED}")
            if r[0] in pos and r[0] not in junk]
    if not rows:
        _pairs = (M, []); return []
    U = [r[0] for r in rows]; D = [r[1] for r in rows]
    Y = np.array([int(d[:4]) for d in D]); lat = np.array([r[2] for r in rows]); lon = np.array([r[3] for r in rows])
    V = M[[pos[u] for u in U]]
    dlat, dlon = NEAR_M / 111_000, NEAR_M / (111_000 * np.cos(np.radians(np.median(lat))))
    cells = {}
    for i in range(len(U)):
        cells.setdefault((int(lat[i] // dlat), int(lon[i] // dlon)), []).append(i)
    cands = []
    blocks = [((a, b), cell[k:k + 512]) for (a, b), cell in cells.items() for k in range(0, len(cell), 512)]
    for (a, b), idx in blocks:  # in blocks, since home can hold thousands
        near = np.array([i for da in (-1, 0, 1) for db in (-1, 0, 1) for i in cells.get((a + da, b + db), [])])
        idx = np.array(idx)
        S = V[idx] @ V[near].T
        metres = np.hypot((lat[idx][:, None] - lat[near][None]) * 111_000,
                          (lon[idx][:, None] - lon[near][None]) * 111_000 * np.cos(np.radians(lat[idx]))[:, None])
        ok = (Y[near][None] - Y[idx][:, None] >= YEARS) & (S >= LOOK_AT) & (S < COPY_AT) & (metres <= NEAR_M)
        cands += [(float(S[x, y]), int(idx[x]), int(near[y])) for x, y in zip(*np.where(ok))]
    cands.sort(key=lambda c: -c[0])
    used, outings, spots, out = set(), [], {}, []
    for s, i, j in cands:
        if i in used or j in used:
            continue
        di, dj = _days(D[i]), _days(D[j])
        if any(abs(di - a) <= SAME_OUTING and abs(dj - b) <= SAME_OUTING for a, b in outings):
            continue
        spot = (round(lat[j], 2), round(lon[j], 2))
        if spots.get(spot, 0) >= PER_SPOT:
            continue
        used |= {i, j}; outings.append((di, dj)); spots[spot] = spots.get(spot, 0) + 1
        out.append((s, U[i], U[j]))
    _pairs = (M, out)
    return out


def then_and_now(con):
    """The pairs for the page: then, now (photo info), and how many years apart."""
    ps = pairs(con)
    info = photo_info(con, [u for _, a, b in ps for u in (a, b)])
    return [dict(then=info[a], now=info[b], years=int(info[b]["date"][:4]) - int(info[a]["date"][:4]), score=round(s, 3))
            for s, a, b in ps]
