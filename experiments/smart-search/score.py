"""Scores keyword rules, Jev and Laya on the labelled searches: cut-offs picked on TUNE, scored on TEST."""
import json, re, sys
from pathlib import Path
HERE = Path(__file__).parent
D = HERE.parent.parent / "data" / "eval" / "smart-search"
sys.path.insert(0, str(HERE))
from queries import TUNE, TEST
import rules
DEFAULT = dict(kind="either", season="none", when="any")
CH = ("kind", "season", "when")
raw = {m: json.load(open(D / f"raw-{m}.json")) for m in ("jev", "laya-classic", "laya-vega")}

def conf(m, a):
    return a["confidence"] if m == "jev" else a.get("answer_confidence", 0)

def answers(m, q, gate, tnp, tns, abstain=False):
    if m == "rules":
        r = rules.answer(q)
    else:
        a = raw[m][q]["answers"]
        r = {k: (a[k]["choice"] if (not abstain or not a[k].get("abstain")) and conf(m, a[k]) >= gate else DEFAULT[k]) for k in CH}
        r["no_people"], r["no_selfies"] = a["no_people"]["noul"] > tnp, a["no_selfies"]["noul"] > tns
    if re.search(r"\b(19[5-9]\d|20\d\d)\b", q):
        r["when"] = "a named year"  # found locally, as smart search does
    return r

def right(row, r):
    q, kind, season, when, np_, ns = row
    return dict(kind=r["kind"] in kind.split("|"), season=r["season"] in season.split("|"), when=r["when"] in when.split("|"),
                no_people=r["no_people"] == bool(np_), no_selfies=r["no_selfies"] == bool(ns))

def score(rows, f):
    s = {k: 0 for k in ("kind", "season", "when", "no_people", "no_selfies")}
    for row in rows:
        for k, v in right(row, f(row[0])).items(): s[k] += v
    return s

def total(s): return sum(s.values())

def mix(choice_f, noul_f):
    return lambda q: {**{k: v for k, v in choice_f(q).items() if k in CH}, **{k: v for k, v in noul_f(q).items() if k not in CH}}

grid = [0, .3, .4, .5, .6, .7, .8, .9]
best = {}
for m in raw:
    cands = [(total(score(TUNE, lambda q: answers(m, q, g, a, b, ab))), g, a, b, ab)
             for g in grid for a in grid[1:] for b in grid[1:] for ab in ((False, True) if m == "laya-vega" else (False,))]
    best[m] = max(cands, key=lambda c: (c[0], -abs(c[2] - .5) - abs(c[3] - .5)))
rows = []
add = lambda name, f: rows.append((name, score(TUNE, f), score(TEST, f)))
add("keyword rules", lambda q: answers("rules", q, 0, 0, 0))
add("Jev as shipped (0.6 / 0.7 / 0.85)", lambda q: answers("jev", q, .6, .7, .85))
for m in raw:
    _, g, a, b, ab = best[m]
    label = f"{m}, tuned (floor {g}, cut-offs {a} / {b}{', abstain' if ab else ''})"
    add(label, lambda q, m=m, g=g, a=a, b=b, ab=ab: answers(m, q, g, a, b, ab))
for m in ("laya-classic", "laya-vega"):
    _, g, a, b, ab = best[m]
    add(f"rules for choices + {m} yes/no", mix(lambda q: answers("rules", q, 0, 0, 0), lambda q, m=m, g=g, a=a, b=b, ab=ab: answers(m, q, g, a, b, ab)))
print(f"{'':58} {'tune /150':>9} {'TEST /150':>9}   test: kind season when no-people no-selfies (each /30)")
for name, t, s in rows:
    print(f"{name:58} {total(t):>9} {total(s):>9}   {s['kind']:>4} {s['season']:>6} {s['when']:>4} {s['no_people']:>9} {s['no_selfies']:>10}")

def misses(f, rows_):
    out = []
    for row in rows_:
        r = f(row[0])
        for k, ok in right(row, r).items():
            if not ok:
                want = dict(zip(("kind", "season", "when", "no_people", "no_selfies"), row[1:]))[k]
                out.append(f"{row[0]!r}: {k} = {r[k]} (wanted {want})")
    return out
_, g, a, b, ab = best["laya-classic"]
for name, f in (("rules", lambda q: answers("rules", q, 0, 0, 0)), ("jev", lambda q: answers("jev", q, .6, .7, .85)),
                ("laya-classic", lambda q: answers("laya-classic", q, g, a, b, ab))):
    print(f"\n{name} misses, TEST:"); print("\n".join("  " + m for m in misses(f, TEST)))
print("\nrules misses, TUNE:"); print("\n".join("  " + m for m in misses(lambda q: answers("rules", q, 0, 0, 0), TUNE)))
