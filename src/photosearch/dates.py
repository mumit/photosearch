"""Date detective: dates for the photos whose date in Photos is a placeholder (scans, a camera with a reset clock).

The photos are dated a group at a time: an album of them, or a loose photo with its closest loose look-alikes. Each
group comes with clues (a date in the album's name, a dated album in the same series, who's in it, which dated photos
it looks like) and a guess, and my answer becomes the date. The dates live in photosearch's index (table `redated`),
never in Photos, and `photosearch index` re-applies them after it refreshes what Photos says.

Look-alikes are a weak clue on their own: hiding each dated album's whole event and guessing its year from the rest
got the year right 25 times in 105 and within a year 58 times.
"""
import json, re, statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from .store import DATED, photo_info, vectors

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
LOOSE_ALIKE = 0.82  # a loose photo's group: the loose photos this close to it, often one evening (I untick any that don't belong)
LOOSE_MAX = 12


def placeholder(con):
    """Photos still on a placeholder date: shared by 50+ photos, or the date Photos had for a photo I've dated."""
    return [r[0] for r in con.execute(f"select uuid from photos where not ({DATED}) order by title, uuid")]


def apply(con):
    """Put my dates back after `photosearch index` refreshed every photo's date from Photos."""
    con.execute("update photos set date = (select r.date from redated r where r.uuid = photos.uuid) "
                "where uuid in (select uuid from redated)")
    con.commit()


def name_date(name):
    """(year, month or None) from an album name like "Bhutan January 2007" or "Summer 2004"."""
    y = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", name)
    if not y:
        return None
    m = re.search(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\b", name.lower())
    return int(y[1]), m and [x[:3] for x in MONTHS].index(m[1]) + 1


def series(name):
    """("Arshan", days in) for "Arshan weeks 4-6": albums named by weeks since some day, so one dated album dates
    the rest."""
    m = re.fullmatch(r"(.+?)\s+weeks?\s+(\d+)(?:\s*-\s*(\d+))?", name.strip(), re.I)
    if not m:
        return None
    a, b = int(m[2]), int(m[3] or m[2])
    return m[1].lower(), round((a + b) / 2 * 7)


def groups(con):
    """The undated photos in groups to date together: [{id, album, uuids}], albums first, then loose photos.

    A photo's group is its smallest album, ignoring albums that also hold dated photos ("for print" mixes years) and
    albums that mostly hold other albums' photos (a "Roll 1" spanning every scan). Photos with no such album are
    loose: each goes with its closest loose look-alikes."""
    und = placeholder(con)
    if not und:
        return []
    rows = {r[0]: (json.loads(r[1]), r[2]) for r in con.execute(
        f"select uuid, albums, title from photos where uuid in ({','.join('?' * len(und))})", und)}
    mixed = {a for (al,) in con.execute(f"select albums from photos where {DATED}") for a in json.loads(al)}
    size = Counter(a for al, _ in rows.values() for a in al if a not in mixed)
    def smaller(u, a):
        return any(b not in mixed and size[b] < size[a] for b in rows[u][0])
    within = defaultdict(list)
    for u in und:
        for a in rows[u][0]:
            within[a].append(u)
    container = {a for a in size if sum(smaller(u, a) for u in within[a]) > len(within[a]) / 2}
    out, loose = defaultdict(list), []
    for u in und:
        own = sorted((a for a in rows[u][0] if a not in mixed and a not in container), key=lambda a: (size[a], a))
        (out[own[0]] if own else loose).append(u)
    order = lambda us: sorted(us, key=lambda u: (rows[u][1] or "", u))  # file names count up as the shots were taken
    result = [dict(id="a:" + a, album=a, uuids=order(us)) for a, us in sorted(out.items(), key=lambda kv: -len(kv[1]))]
    if loose:
        uuids, M, pos = vectors(con)
        left = [u for u in order(loose) if u in pos]
        L = M[[pos[u] for u in left]]
        free = np.ones(len(left), bool)
        for i, u in enumerate(left):
            if not free[i]:
                continue
            sims = L @ L[i]
            near = [j for j in np.argsort(-sims) if free[j] and sims[j] >= LOOSE_ALIKE][:LOOSE_MAX]
            near = near if i in near else [i] + near[: LOOSE_MAX - 1]
            free[near] = False
            result.append(dict(id="p:" + u, album=None, uuids=order([left[j] for j in near])))
    return result


def clues(con, g, k=10):
    """What points to a date for this group, strongest first, and the guess they make: {guess, clues, alike}."""
    out, guess = [], None
    if g["album"] and (nd := name_date(g["album"])):
        y, m = nd
        guess = dict(year=y, month=m, how="the album name")
        out.append(f"The album is called “{g['album']}”.")
    if g["album"] and (s := series(g["album"])) and not guess:
        for sib, d in series_dates(con).items():
            if series(sib)[0] == s[0]:
                when = d + timedelta(days=s[1] - series(sib)[1])
                guess = dict(year=when.year, month=when.month, how=f"“{sib}”, already dated")
                out.append(f"“{sib}” is dated {d:%B %Y}, so “{g['album']}” is {abs(s[1] - series(sib)[1]) // 7} weeks "
                           f"{'later' if s[1] > series(sib)[1] else 'earlier'}.")
                break
        else:
            out.append(f"“{g['album']}” is one of a series named by weeks: date one and I'll work out the others.")
    who = Counter(p for (ps,) in con.execute(f"select persons from photos where uuid in ({','.join('?' * len(g['uuids']))})",
                                             g["uuids"]) for p in json.loads(ps))
    for p, _ in who.most_common(3):
        first, last = con.execute(f"select min(substr(date,1,4)), max(substr(date,1,4)) from photos where {DATED} and "
                                  "exists (select 1 from json_each(persons) where value = ?)", (p,)).fetchone()
        if first:
            out.append(f"{p} is in dated photos from {first}" + (f" to {last}." if last != first else "."))
    uuids, M, pos = vectors(con)
    dated = [r[0] for r in con.execute(f"select uuid from photos where {DATED}") if r[0] in pos]
    alike = []
    if dated:
        D = M[[pos[u] for u in dated]]
        when = dict(con.execute(f"select uuid, substr(date,1,10) from photos where {DATED}"))
        votes, best = Counter(), Counter()
        for u in g["uuids"][:60]:
            if u not in pos:
                continue
            s = D @ M[pos[u]]
            for j in np.argpartition(-s, min(k, len(s) - 1))[:k]:
                votes[int(when[dated[j]][:4])] += float(s[j]) ** 4
                best[dated[j]] = max(best[dated[j]], float(s[j]))
        if votes:
            y, v = votes.most_common(1)[0]
            share = v / sum(votes.values())
            out.append(f"It looks most like dated photos from {y} ({share:.0%} of the look-alikes), a weak clue.")
            alike = [u for u, _ in best.most_common(4)]
            if not guess:
                guess = dict(year=y, month=None, how="look-alikes")
    return dict(guess=guess, clues=out, alike=list(photo_info(con, alike).values()) if alike else [])


def series_dates(con):
    """{album: date} for the albums in a series (named by weeks) that I've dated."""
    out = defaultdict(list)
    for al, d in con.execute("select p.albums, r.date from redated r join photos p using(uuid)"):
        for a in json.loads(al):
            if series(a):
                out[a].append(date.fromisoformat(d[:10]))
    return {a: statistics.median_low(ds) for a, ds in out.items()}


def next_group(con, skip=()):
    """The next group to date, with its photos and clues, and how many photos are left: groups with a strong clue
    first, then the largest."""
    gs = groups(con)
    left, total = sum(len(g["uuids"]) for g in gs), len(gs)
    gs = [g for g in gs if g["id"] not in set(skip)] or gs
    if not gs:
        return dict(left=0, groups=0, group=None)
    scored = []
    for i, g in enumerate(gs[:40]):
        c = clues(con, g)
        strong = c["guess"] and c["guess"]["how"] != "look-alikes"
        scored.append((not strong, -len(g["uuids"]), i, g, c))
        if strong:
            break
    _, _, _, g, c = min(scored, key=lambda t: t[:3])
    info = photo_info(con, g["uuids"])
    return dict(left=left, groups=total, group=dict(id=g["id"], album=g["album"], photos=[info[u] for u in g["uuids"]], **c))


def set_date(con, uuids, year, month=None, day=None, how="me, in the date detective"):
    """Date these photos: the day given, else the 15th of the month, else July 1st (and say how sure). In file-name
    order a minute apart, so a story shows them in the order they were taken. Returns how many."""
    year, month, day = int(year), month and int(month), day and int(day)
    start = datetime(year, month or 7, day or (15 if month else 1), 12)
    precision = "day" if day else "month" if month else "year"
    have = {r[0]: r[1:] for r in con.execute(
        f"select p.uuid, p.date, p.title, r.photos_date from photos p left join redated r using(uuid) "
        f"where p.uuid in ({','.join('?' * len(uuids))})", list(uuids))}
    if missing := [u for u in uuids if u not in have]:
        raise LookupError(f"{len(missing)} of those photos aren't in the index")
    at = datetime.now().isoformat(timespec="seconds")
    for i, u in enumerate(sorted(have, key=lambda u: (have[u][1] or "", u))):
        old, _, photos_date = have[u]
        tz = re.search(r"([+-]\d\d:\d\d|Z)$", old)
        when = (start + timedelta(minutes=i)).isoformat() + (tz[1] if tz else "")
        con.execute("insert or replace into redated values(?,?,?,?,?,?)", (u, when, photos_date or old, precision, how, at))
        con.execute("update photos set date=? where uuid=?", (when, u))
    con.commit()
    return len(have)


def undo(con, uuids=None):
    """Back to the date Photos has, for these photos or all of them. Returns how many."""
    rows = con.execute("select uuid, photos_date from redated" + (f" where uuid in ({','.join('?' * len(uuids))})" if uuids else ""),
                       list(uuids or [])).fetchall()
    for u, d in rows:
        con.execute("update photos set date=? where uuid=?", (d, u))
        con.execute("delete from redated where uuid=?", (u,))
    con.commit()
    return len(rows)


def approx(con, uuids):
    """{uuid: "month" | "year"} for the photos I dated less exactly than a day."""
    return dict(con.execute(f"select uuid, precision from redated where precision != 'day' and uuid in "
                            f"({','.join('?' * len(uuids))})", list(uuids)))


def parse_when(s):
    """"2007", "2007-01" or "2007-01-15" → (year, month, day)."""
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s.strip())
    if not m:
        raise SystemExit(f"not a date: {s!r} (2007, 2007-01 or 2007-01-15)")
    y, mo, d = int(m[1]), m[2] and int(m[2]), m[3] and int(m[3])
    try:
        date(y, mo or 1, d or 1)
    except ValueError as ex:
        raise SystemExit(f"not a date: {s!r} ({ex})")
    return y, mo, d


def cmd_dates(a):
    from .store import db
    con = db()
    if a.do == "set":
        g = next((g for g in groups(con) if g["id"] == a.group or g["album"] == a.group), None)
        if not g:
            raise SystemExit(f"no undated group {a.group!r}; `photosearch dates` lists them")
        print(f"dated {set_date(con, g['uuids'], *parse_when(a.when), how='me, from the terminal')} photos")
    elif a.do == "undo":
        if a.group == "all":
            n = undo(con)
        else:
            us = [u for (u, al) in con.execute("select uuid, albums from photos where uuid in (select uuid from redated)")
                  if a.group in json.loads(al) or u == a.group.removeprefix("p:")]
            n = undo(con, us) if us else 0
        print(f"{n} photos back to the date Photos has")
    else:
        gs = groups(con)
        print(f"{sum(len(g['uuids']) for g in gs)} photos without a real date, in {len(gs)} groups")
        for g in gs[: a.limit]:
            c = clues(con, g)
            gu = c["guess"]
            say = f"{gu['year']}" + (f"-{gu['month']:02}" if gu["month"] else "") + f" from {gu['how']}" if gu else "no guess"
            print(f"  {len(g['uuids']):4}  {g['album'] or g['id']:32}  {say}")
        print("date one: photosearch dates set GROUP 2007-01   (GROUP is an album name, or p:... for loose photos)")
