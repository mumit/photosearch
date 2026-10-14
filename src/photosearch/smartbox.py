"""The optional smart search box: TypeSafe Jev reads filters (season, dates, no selfies) out of plain words."""
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
    """TYPESAFE_API_KEY from the environment, or from a .env file in the checkout."""
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


def parse_query(con, text, today=None):
    """Turn "Sam at the beach last summer, no selfies" into search filters. Names and years are found locally;
    the rest is asked of Jev, which only ever sees the text with tagged names replaced by "someone"."""
    today = today or date.today()
    people = sorted({p for (j,) in con.execute("select persons from photos") for p in json.loads(j)}, key=len, reverse=True)
    firsts = Counter(p.split()[0].lower() for p in people)
    found, masked = [], text
    for p in people:  # full names first, then unambiguous first names
        for name in [p] + ([p.split()[0]] if " " in p and firsts[p.split()[0].lower()] == 1 else []):
            pat = re.compile(rf"\b{re.escape(name)}\b", re.I)
            if pat.search(masked):
                masked = pat.sub("someone", masked); found.append(p); break
    a = ask_jev(masked)
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
    return f
