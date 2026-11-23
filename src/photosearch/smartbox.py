"""The smart search box: filters (photo or video, season, dates, no people, no selfies) read out of plain words. With a
TypeSafe key Jev reads them; without one, or when Jev can't answer, keyword rules do, on this Mac. On 40 searches
their author never saw, the rules got 196 of 200 answers right and Jev 198 (FINDINGS.md, Smart search without Jev)."""
import functools, json, os, re
from collections import Counter
from datetime import date, timedelta

from .config import ROOT
from .search import SEASONS

JEV_URL = "https://api.typesafe.ai/v1/systemone"
# Cut-offs picked on 20 labelled queries, then checked on 20 fresh ones (95/100 answers right).
NO_PEOPLE_P, NO_SELFIES_P, CHOICE_P = 0.7, 0.85, 0.6
JEV_QUESTIONS = {
    "kind": {"type": "choice", "instructions": "Does the user want photos, videos, or either?",
             "criteria": {"photo": "explicitly asks for photos/pictures only", "video": "asks for videos, clips or footage",
                          "either": "doesn't say"}},
    "season": {"type": "choice", "instructions": "Which season of the year does the search mention?",
               "criteria": {"none": "no season mentioned", "spring": "spring", "summer": "summer", "autumn": "fall or autumn",
                            "winter": "winter"}},
    "when": {"type": "choice", "instructions": "What time period does the search ask for?",
             "criteria": {"any": "no time period", "this year": "this year", "last year": "last year",
                          "a named year": "a specific year like 2019",
                          "recent": "recently, lately, the last few weeks or months",
                          "long ago": "years ago, when the kids were little, old photos"}},
    "no_people": {"type": "noul", "instructions": "Does the user want photos WITHOUT people in them?"},
    "no_selfies": {"type": "noul", "instructions": "Does the user want to EXCLUDE selfies?"},
}


def jev_key():
    """TYPESAFE_API_KEY from the environment, or from a .env file next to data/ (config.ROOT)."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    f = ROOT / ".env"
    for line in f.read_text().splitlines() if f.exists() else []:
        if line.strip().startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


@functools.lru_cache(maxsize=256)
def ask_jev(text):
    import urllib.request
    req = urllib.request.Request(JEV_URL, method="POST", headers={"Authorization": f"Bearer {jev_key()}",
                                                                  "Content-Type": "application/json"},
                                 data=json.dumps(dict(model="jev-latest", state=text, questions=JEV_QUESTIONS)).encode())
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.load(r)["answers"]


# The keyword rules (experiments/smart-search/ has the first version, as measured). Change them only with a new set of
# fresh searches to check them on: the ones they were measured on have been seen.
NOT = r"\b(no|not|without|minus|skip|but not|except)( the| any)? "


def _kind(q):
    if re.search(r"\b(only|just) (the )?(photos?|pictures?|pics?|stills?)\b|\bphotos? only\b|" + NOT + r"(videos?|clips?|movies?)\b", q, re.I):
        return "photo"
    if re.search(r"\b(only|just) (the )?(videos?|clips?)\b|\bvideos? only\b|" + NOT + r"(photos?|pictures?|pics?)\b", q, re.I):
        return "video"
    q = re.sub(r"\bvideo ?games?\b|\bmovie (night|theat(er|re)|poster|tickets?)\b|\bat the movies\b", "", q, flags=re.I)
    if re.search(r"\b(videos?|vids?|clips?|footage|movies?|filmed|filming|recordings?|recorded)\b", q, re.I):
        return "video"
    return "either"


def _season(q):
    for s, pat in (("spring", r"\bspring(time)?\b(?! (roll|water|onion))"), ("summer", r"\bsummer(time|s)?\b"),
                   ("autumn", r"\bautumn\b|\bfall\b(?! (down|over|off|asleep))"), ("winter", r"\bwinter(time|s)?\b")):
        if re.search(pat, q, re.I):
            return s
    return "none"


def _when(q, today):
    if re.search(r"\bthis (year|spring|summer|fall|autumn|winter)\b", q, re.I):
        return "this year"
    if re.search(r"\blast (year|yr)\b|\ba year ago\b", q, re.I):
        return "last year"
    if m := re.search(r"\blast (spring|summer|fall|autumn|winter)\b", q, re.I):  # the latest one that's over
        months = SEASONS["autumn" if m.group(1).lower() == "fall" else m.group(1).lower()]
        return "this year" if today.month not in months and today.month > months[-1] else "last year"
    if re.search(r"\b(recent(ly)?|lately|latest|newest|this (month|week)|(last|past) (few |couple( of)? )?(days|weeks?|months?))\b",
                 q, re.I):
        return "recent"
    if re.search(r"\b(years ago|long ago|ages ago|back in the day|old (photos?|pictures?|pics?|videos?)|"
                 r"when (the )?(kids|someone|we|i|they|he|she) (were|was) (a )?(little|young|small|tiny|bab(y|ies)|toddlers?|kids?))\b",
                 q, re.I):
        return "long ago"
    return "any"


def _no_people(q):
    return bool(re.search(r"\b(no|without|w/o|minus|free of|zero) (any )?(people|persons?|humans?|anyone|anybody|crowds?|faces?|"
                          r"one in (it|them))\b|\bnobody\b|\bno one\b|\bpeople-?free\b|\bempty\b|\bdeserted\b|"
                          r"\bjust (the )?(scenery|landscapes?|views?)\b", q, re.I))


def _no_selfies(q):
    return bool(re.search(r"\b(no|without|not|skip|exclude|excluding|minus|except|but no|leave out|other than) "
                          r"(the |any |my )?(selfies?|self[- ]portraits?)\b", q, re.I))


def read_words(text, today=None):
    """JEV_QUESTIONS answered by the keyword rules, in Jev's shape (choices are sure, yes/no is 1 or 0)."""
    choice = lambda c: dict(choice=c, confidence=1.0)
    return dict(kind=choice(_kind(text)), season=choice(_season(text)), when=choice(_when(text, today or date.today())),
                no_people=dict(noul=float(_no_people(text))), no_selfies=dict(noul=float(_no_selfies(text))))


def mask(con, text):
    """(the tagged people named in text, text with each of them replaced by "someone"): Jev never sees a name."""
    people = sorted({p for (j,) in con.execute("select persons from photos") for p in json.loads(j)}, key=len, reverse=True)
    firsts = Counter(p.split()[0].lower() for p in people)
    found, masked = [], text
    for p in people:  # full names first, then unambiguous first names
        for name in [p] + ([p.split()[0]] if " " in p and firsts[p.split()[0].lower()] == 1 else []):
            pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
            if pat.search(masked):
                masked = pat.sub("someone", masked); found.append(p); break
    return found, masked


def parse_query(con, text, today=None):
    """Turn "Sam at the beach last summer, no selfies" into search filters, and who read them ("jev" or "rules").
    Names and years are found locally; the rest is asked of Jev if there's a key, which only ever sees the text with
    tagged names replaced by "someone", else of the keyword rules."""
    today = today or date.today()
    found, masked = mask(con, text)
    a, by = None, "rules"
    if jev_key():
        try:
            a, by = ask_jev(masked), "jev"
        except Exception:  # offline, a bad key, a rate limit: the rules still read it
            pass
    a = a or read_words(masked, today)
    pick = lambda k: a[k]["choice"] if a[k].get("confidence", 1) >= CHOICE_P else None
    f = dict(person=", ".join(found), kind="", after="", before="", season="", exclude="")
    if pick("kind") in ("photo", "video"):
        f["kind"] = pick("kind")
    if pick("season") in SEASONS:
        f["season"] = pick("season")
    year = re.search(r"\b(19[5-9]\d|20\d\d)\b", text)
    when = "a named year" if year else pick("when")
    y = int(year.group(1)) if year else {"this year": today.year, "last year": today.year - 1}.get(when)
    if y:
        f["after"], f["before"] = f"{y}-01-01", f"{y + 1}-01-01"
        if when == "this year":
            f["before"] = ""
    elif when == "recent":
        f["after"] = (today - timedelta(days=120)).isoformat()
    elif when == "long ago":
        f["before"] = today.replace(year=today.year - 5).isoformat()
    f["exclude"] = ", ".join(x for x, q, p in (("people", "no_people", NO_PEOPLE_P), ("a selfie", "no_selfies", NO_SELFIES_P))
                             if a[q]["noul"] > p)
    return f, by
