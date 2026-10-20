"""The people tagged in Photos: who, their best portrait (or the one I chose), their page."""
import hashlib, io, json
from collections import Counter, defaultdict
from datetime import datetime

from . import embed
from .config import DATA, LARGE
from .images import open_image
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
    mine = chosen(con)
    return [dict(name=p, n=c, cover=mine.get(p) or (portraits(con, rows[p]) if rows[p] else None)) for p, c in count.most_common(n)]


def chosen(con):
    """{name: uuid}: the portraits I chose, while the photo is still indexed and still has them tagged."""
    return {n: u for n, u in con.execute("select name, uuid from portrait where exists (select 1 from photos p where "
                                         "p.uuid = portrait.uuid and exists (select 1 from json_each(p.persons) where value = name))")}


def choose(con, name, uuid):
    """Use this photo as someone's portrait everywhere (Home, their page, the photo frame). No uuid: back to the one
    picked for them."""
    if not uuid:
        con.execute("delete from portrait where name=?", (name,)); con.commit()
        return dict(name=name, cover=None)
    row = con.execute("select persons, kind from photos where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(f"{uuid} not indexed")
    if row[1] != "photo" or name not in json.loads(row[0]):
        raise ValueError(f"{name} isn't tagged in that photo")
    con.execute("insert or replace into portrait values(?,?,?)", (name, uuid, datetime.now().isoformat())); con.commit()
    return dict(name=name, cover=uuid)


FACES = DATA / "faces"
FACE_PX, FACE_ROOM = 320, 2.4  # the crop is FACE_ROOM times the face, so hair and chin fit in the circle


def face(con, uuid, name):
    """A square JPEG around name's face in the photo, from its largest copy on this Mac; None if Photos doesn't say
    where their face is (then the whole thumbnail does)."""
    row = con.execute("select src, faces from photos where uuid=?", (uuid,)).fetchone()
    spot = json.loads(row[1] or "{}").get(name) if row else None
    if not spot:
        return None
    f = FACES / f"{uuid}-{hashlib.sha1(json.dumps([name, spot]).encode()).hexdigest()[:10]}.jpg"
    if f.exists():
        return f.read_bytes()
    big = LARGE / f"{uuid}.jpg"
    try:
        im = open_image(big if big.exists() else row[0], 1600)
    except OSError:  # the preview is gone from the Photos library
        return None
    x, y, size = spot
    w, h = im.size
    side = min(w, h, max(64, size * max(w, h) * FACE_ROOM))
    left = min(max(0, x * w - side / 2), w - side); top = min(max(0, y * h - side / 2), h - side)
    out = im.crop((round(left), round(top), round(left + side), round(top + side))).resize((FACE_PX, FACE_PX))
    buf = io.BytesIO(); out.save(buf, "JPEG", quality=85)
    FACES.mkdir(parents=True, exist_ok=True); f.write_bytes(buf.getvalue())
    return buf.getvalue()


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
    portrait = chosen(con).get(name) or (portraits(con, faces) if faces else None)
    return dict(name=name, n=len(rows), first=dates[0], last=dates[-1], portrait=portrait,
                years=[dict(info[u], year=int(y)) for y, (_, u) in sorted(by_year.items())],
                together=with_.most_common(8), places=places.most_common(8))
