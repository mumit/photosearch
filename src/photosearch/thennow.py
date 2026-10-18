"""Then and now: two photos from the same spot, years apart, that look alike (the same lookout, the pool in the snow).

A pair is two photos within NEAR_M of each other by GPS, at least YEARS apart, as alike as LOOK_AT. Set by eye on
a 16,000-photo library, from sheets of the best pairs:
- Matching by look alone, without GPS on the older photo, found different places that look alike (Angkor Wat and
  Teotihuacan, two aquariums), so both photos need GPS. Here that means 2016 on.
- Above 0.97 they're copies of one photo; below LOOK_AT, two photos that merely share a park.
- Clutter (an ID shot twice, floors, price tags) and repeat outings (the same two days, a week either side) are left
  out, and a spot gives at most PER_SPOT pairs, so home doesn't fill the list.
- The scene decides, not who's in it, so a spot's pair is often one child, then a younger sibling years later.

Same person: two photos where Photos names the same person, years apart, as alike as PERSON_AT. Names don't need GPS,
so these reach back to the scans. In photos with more named people, or below PERSON_AT, the pairs were parties: one
face among many in a dining room that looks like every other dining room.
"""
import json

import numpy as np

from .clutter import found as clutter_found
from .store import DATED, photo_info, vectors

NEAR_M = 150
YEARS = 4
LOOK_AT, COPY_AT = 0.80, 0.97
SAME_OUTING = 7  # days
PER_SPOT = 3  # pairs per ~1 km
PERSON_AT, MAX_NAMED, PER_PERSON = 0.88, 2, 12
_pairs = (None, None)
_people = (None, None)


def _days(d):
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return y * 372 + m * 31 + dd


def pairs(con):
    """[(score, then, now)], best first."""
    global _pairs
    _, M, pos = vectors(con)
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
        cands += [(float(S[x, y]), (round(lat[near[y]], 2), round(lon[near[y]], 2)), U[idx[x]], U[near[y]], D[idx[x]], D[near[y]])
                  for x, y in zip(*np.where(ok))]
    out = [(s, a, b) for s, _, a, b, _, _ in _choose(cands, PER_SPOT)]
    _pairs = (M, out)
    return out


def _choose(cands, most):
    """The best of [(score, key, then, now, then's date, now's date)]: each photo and each pair of outings once, at
    most `most` per key (a spot, a person)."""
    cands.sort(key=lambda c: -c[0])
    used, outings, per, out = set(), [], {}, []
    for c in cands:
        s, k, i, j, di, dj = c
        if i in used or j in used or per.get(k, 0) >= most:
            continue
        di, dj = _days(di), _days(dj)
        if any(abs(di - a) <= SAME_OUTING and abs(dj - b) <= SAME_OUTING for a, b in outings):
            continue
        used |= {i, j}; outings.append((di, dj)); per[k] = per.get(k, 0) + 1
        out.append(c)
    return out


def person_pairs(con):
    """[(score, name, then, now)], best first."""
    global _people
    _, M, pos = vectors(con)
    if _people[0] is M:
        return _people[1]
    junk = {u for v in clutter_found(con).values() for u in v}
    by = {}
    for u, d, p in con.execute(f"select uuid, date, persons from photos where kind='photo' and persons!='[]' and {DATED}"):
        names = json.loads(p)
        if u in pos and u not in junk and len(names) <= MAX_NAMED:
            for n in names:
                by.setdefault(n, []).append((u, d))
    cands = []
    for name, ph in by.items():
        U = [u for u, _ in ph]; D = [d for _, d in ph]; Y = np.array([int(d[:4]) for d in D])
        V = M[[pos[u] for u in U]]
        for k in range(0, len(U), 512):
            S = V[k:k + 512] @ V.T
            ok = (Y[None] - Y[k:k + 512, None] >= YEARS) & (S >= PERSON_AT) & (S < COPY_AT)
            cands += [(float(S[x, y]), name, U[k + x], U[y], D[k + x], D[y]) for x, y in zip(*np.where(ok))]
    out = [(s, n, a, b) for s, n, a, b, _, _ in _choose(cands, PER_PERSON)]
    _people = (M, out)
    return out


def then_and_now(con, person=False):
    """The pairs for the page: then, now (photo info), how many years apart, and for the same person, who."""
    ps = person_pairs(con) if person else [(s, None, a, b) for s, a, b in pairs(con)]
    info = photo_info(con, [u for _, _, a, b in ps for u in (a, b)])
    return [dict(then=info[a], now=info[b], years=int(info[b]["date"][:4]) - int(info[a]["date"][:4]), score=round(s, 3),
                 **({"who": n} if n else {})) for s, n, a, b in ps]
