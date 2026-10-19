"""Search by words or by example, with filters, and how interesting each photo looks."""
import numpy as np

from . import embed, videos
from .store import photo_info, vec_of, vectors


def filtered(con, person=None, after=None, before=None, kind=None, place=None, months=None):
    """person: a name or a list of names (all must be in the photo); names and place match on substrings.
    months: month numbers to keep, e.g. (6, 7, 8) for summer."""
    clauses, params = [], []
    for name in [person] if isinstance(person, str) else person or []:
        clauses.append("exists (select 1 from json_each(persons) where lower(value) like ?)"); params.append(f"%{name.lower()}%")
    if place:
        clauses.append("lower(place) like ?"); params.append(f"%{place.lower()}%")
    if months:
        clauses.append(f"cast(substr(date,6,2) as integer) in ({','.join('?' * len(months))})"); params.extend(months)
    if after:
        clauses.append("date >= ?"); params.append(after)
    if before:
        clauses.append("date < ?"); params.append(before)
    if kind:
        clauses.append("kind = ?"); params.append(kind)
    uuids, M, pos = vectors(con)
    if not clauses:
        return uuids, M
    keep = [r[0] for r in con.execute("select uuid from photos where " + " and ".join(clauses), params)]
    keep = [u for u in keep if u in pos]
    return keep, M[[pos[u] for u in keep]]


# Some photos come up for almost any words: accidental shots, black frames, close textures (leaves, rocks, dry
# grass). Each loses up to HUB_W by how many first pages (HUB_K) it is in when Photos' own labels are searched for,
# counted up to HUB_CAP. Judged blind on 115 searches, the photos this changes in the first 10 fit better: 98
# coming in against 75 going out, most where search was weakest (dark, black-and-white, dusk, printed pages).
HUB_W, HUB_K, HUB_CAP, HUB_WORDS = 0.04, 24, 40, 100
_hubs = (None, None)

def hub_penalty(con):
    """{uuid: how much to take off its score for words}, from the photos that match everything."""
    global _hubs
    uuids, M, _ = vectors(con)
    if _hubs[0] is not M:
        from .why import vocab
        _, V = vocab(con)
        pen = {}
        if len(V) >= HUB_WORDS and len(uuids) > HUB_K:  # too few labels (a new library) to tell
            top = np.argpartition(-(V @ M.T), HUB_K, axis=1)[:, :HUB_K]
            n = np.bincount(top.ravel(), minlength=len(uuids))
            pen = {uuids[i]: HUB_W * min(int(n[i]), HUB_CAP) / HUB_CAP for i in np.nonzero(n)[0]}
        _hubs = (M, pen)
    return _hubs[1]


def rank(con, qvec, k, sounds=False, words=False, **filters):
    """A video scores by its best moment (videos.py): a later frame, or with sounds, what's heard. at: when.
    words: qvec is a search for words, so photos that match everything count for less (hub_penalty)."""
    uuids, M = filtered(con, **filters)
    if not uuids:
        return []
    scores, at = M @ qvec, {}
    if words and (pen := hub_penalty(con)):
        scores = scores - np.array([pen.get(u, 0.0) for u in uuids], np.float32)
    if filters.get("kind") != "photo":
        mo = videos.moments(con, qvec, sounds)
        if mo:
            pos = {u: i for i, u in enumerate(uuids)}
            for u, (s, t, heard, frame) in mo.items():
                i = pos.get(u)
                if i is not None and s > scores[i]:
                    scores[i] = s
                    if t or heard:  # the first frame is the poster
                        at[u] = dict(at=t, heard=heard, frame=frame)
    top = np.argsort(-scores)[:k]
    info = photo_info(con, [uuids[i] for i in top])
    return [dict(info[uuids[i]], score=float(scores[i]), **at.get(uuids[i], {})) for i in top]


EXCLUDE_W = 0.5  # how hard `exclude` pushes away; tested on "group photos at a party" minus "a selfie"

def search(con, query, k=24, exclude=None, **f):
    """exclude: what the photos should NOT show ("a selfie", or a list). The model is weak at negation inside the
    query ("no selfies"), so each is subtracted from the query vector instead, as in photo_math."""
    q = embed.embed_query(query)
    for x in [exclude] if isinstance(exclude, str) else exclude or []:
        q = q - EXCLUDE_W * embed.embed_query(x)
    if exclude:
        q = (q / np.linalg.norm(q)).astype(np.float32)
    return rank(con, q, k, sounds=True, words=True, **f)


def similar(con, uuid, k=24, **f):
    return [r for r in rank(con, vec_of(con, uuid), k + 1, **f) if r["uuid"] != uuid][:k]
SEASONS = {"spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11), "winter": (12, 1, 2)}


INTERESTING = ["people at a party or celebration", "a family on vacation", "a beautiful landscape", "kids playing",
               "a city street while travelling", "friends sharing a meal", "a festival or event", "a group photo",
               "a famous landmark", "animals"]
BORING = ["a screenshot of a phone screen", "a photo of a document, receipt or paper", "a dark blurry photo",
          "a whiteboard or a sign with text", "an object photographed for reference", "a photo of a computer screen",
          "a photo of an ID card, passport or credit card"]
_interest = (None, None)

def interest(con):
    """How game-worthy each photo looks: closer to INTERESTING than to BORING."""
    global _interest
    uuids, M, _ = vectors(con)
    if _interest[0] is not M:
        good = np.stack([embed.embed_query(t) for t in INTERESTING]); bad = np.stack([embed.embed_query(t) for t in BORING])
        _interest = (M, (M @ good.T).max(1) - (M @ bad.T).max(1))
    return _interest[1]


def best_of(con, k=48, **f):
    """No words to search for, only filters (a person, a place, a season): their most interesting photos."""
    keep, _ = filtered(con, **f)
    uuids, _, pos = vectors(con)
    score = interest(con)
    top = sorted(keep, key=lambda u: -score[pos[u]])[:k]
    info = photo_info(con, top)
    return [dict(info[u], score=float(score[pos[u]])) for u in top]


# Highlights never include photos that look more boring than interesting (interest below 0: ~10% of the library,
# mostly documents, screenshots and ID cards), even when a day has nothing else: better no photo than a passport.
MIN_INTEREST = 0.0
