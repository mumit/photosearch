"""How much of each search's first 10 photos meets what the search asked for (photo or video, season, time), from
each photo's own date and kind: no judging. Reads the `photosearch eval` runs `box` (search against search=rules)
and `box-jev` (search=rules against search=jev), made from eval_searches.txt on 2026-11-22. No people and no
selfies can't be read from a photo's details, so they're left to the judges."""
import json, re, sqlite3, sys
from datetime import date, timedelta
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from queries import FRESH, FRESH2

DATA = HERE.parent.parent / "data"
TODAY = date(2026, 11, 22)
SEASON_MONTHS = {"spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11), "winter": (12, 1, 2)}
LABELS = {r[0]: r for r in FRESH + FRESH2}
con = sqlite3.connect(f"file:{DATA}/index.sqlite?mode=ro", uri=True)
info = {u: (d, k) for u, d, k in con.execute("select uuid, date, kind from photos")}


def checks(row):
    """The tests a photo must pass for this search: only for questions where the plain answer is wrong."""
    q, kind, season, when, *_ = row
    out = []
    if "either" not in kind.split("|"):
        out.append(lambda d, k, want=set(kind.split("|")): k in want)
    if "none" not in season.split("|"):
        months = {m for s in season.split("|") for m in SEASON_MONTHS[s]}
        out.append(lambda d, k: int(d[5:7]) in months)
    if "any" not in when.split("|"):
        year = re.search(r"\b(19[5-9]\d|20\d\d)\b", q) or re.search(r"\b'?(\d\d)\b", q)
        def ok(d, k, opts=when.split("|")):
            day = date.fromisoformat(d[:10])
            return any({"this year": day.year == TODAY.year, "last year": day.year == TODAY.year - 1,
                        "a named year": bool(year) and day.year == (int(year.group(1)) if len(year.group(1)) == 4 else 2000 + int(year.group(1))),
                        "recent": day >= TODAY - timedelta(days=120),
                        "long ago": day <= TODAY.replace(year=TODAY.year - 5)}[o] for o in opts)
        out.append(ok)
    return out


def meets(uuids, row, n=10):
    tests = checks(row)
    return sum(all(t(*info[u]) for t in tests) for u in uuids[:n]), min(n, len(uuids))


pages = {}
for name, (a, b) in (("box", ("plain", "rules")), ("box-jev", ("rules", "jev"))):
    for p in json.load(open(DATA / "eval" / name / "run.json"))["searches"]:
        pages.setdefault(p["q"], {})[a], pages[p["q"]][b] = p["A"], p["B"]
rows = [LABELS[q] for q in pages if checks(LABELS[q])]
print(f"{len(rows)} of {len(pages)} searches ask for something a photo's details can show (the rest: no people or no selfies only)")
for v in ("plain", "rules", "jev"):
    got = [meets(pages[r[0]][v], r) for r in rows]
    shown = sum(s for _, s in got)
    print(f"  {v:6} first 10 that meet it: {sum(m for m, _ in got)} of {10 * len(rows)}  "
          f"({sum(m for m, _ in got) / (10 * len(rows)):.0%}; {shown} photos shown, {sum(s == 0 for _, s in got)} empty pages)")
if "-v" in sys.argv:
    for r in rows:
        print(f"  {r[0][:60]:60}", "  ".join(f"{v} {meets(pages[r[0]][v], r)[0]:>2}/{meets(pages[r[0]][v], r)[1]:<2}" for v in ("plain", "rules", "jev")))
