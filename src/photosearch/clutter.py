"""Tidying up clutter: screenshots, IDs and cards, receipts and papers, accidental shots. Each kind can go to its own
album in Photos to look through there. Nothing is deleted.

A photo is of a kind when it's closer to that kind's words than to the best of search.INTERESTING by at least the
kind's cut-off. The cut-offs were set by eye on a 17,000-photo library, from sheets of photos at each rank and
around each cut-off:
- IDs and cards, 0.06 (76 photos): IDs, passports, vaccine cards, insurance papers; ordinary portraits by 0.03.
- Receipts and papers, 0.05 (312): receipts, notes, whiteboards, price tags, appliance labels; some plain rooms.
- Accidental shots, 0.07 (30): floors, black frames, blurs. Below that come photos of rooms and repairs, which may
  be worth keeping, and blur or darkness alone also finds dim family photos, so neither is used.
Screenshots come from Photos, which marks them (`flags`); before the index has that, from their phone-screen shape
(139 of 149 such photos were screenshots). Photos marked 163, and of the 24 not phone-shaped, 22 were screenshots too.
"""
import json

import numpy as np

from . import embed, photos_app
from .dupes import CLEANUP, cleanup_state
from .search import INTERESTING
from .store import aspect, photo_info, vectors

KINDS = {  # in order: a photo that fits two kinds is the first (an ID's screenshot is an ID)
    "ids": dict(name="IDs and cards", few="IDs and cards", album="Photosearch · IDs and cards", cut=0.06,
                words=["a photo of an ID card", "a passport photo page", "a photo of a credit card", "a driver's licence card"]),
    "screenshots": dict(name="Screenshots", few="screenshots", album="Photosearch · screenshots"),
    "papers": dict(name="Receipts and papers", few="receipts and papers", album="Photosearch · receipts and papers", cut=0.05,
                   words=["a photo of a receipt", "a long paper store receipt", "a photo of a document or a letter",
                          "a page of handwritten notes", "a photo of a whiteboard", "a printed form"]),
    "accidents": dict(name="Accidental shots", few="accidental shots", album="Photosearch · accidental shots", cut=0.07,
                      words=["an accidental photo taken inside a pocket", "a blurry photo of the floor", "a completely black photo"]),
}
SCREEN_SHAPE = (0.44, 0.48)  # a phone screen, 1170 x 2532 and the like
_found = (None, None)


def found(con):
    """{kind: [uuid, ...]}, the closest first. Videos are left out."""
    global _found
    uuids, M, _ = vectors(con)
    if _found[0] is M:
        return _found[1]
    rows = {u: (k, f) for u, k, f in con.execute("select uuid, kind, flags from photos")}
    photo = np.array([rows.get(u, ("video",))[0] == "photo" for u in uuids], bool)
    base = (M @ np.stack([embed.embed_query(t) for t in INTERESTING]).T).max(1)
    flagged = any(rows[u][1] is not None for u in uuids if u in rows)
    taken, out = np.zeros(len(uuids), bool), {}
    for kind, k in KINDS.items():
        if kind == "screenshots":
            if flagged:
                hit = np.array(["screenshot" in json.loads(rows[u][1] or "[]") for u in uuids], bool)
            else:
                hit = np.array([SCREEN_SHAPE[0] <= aspect(u) <= SCREEN_SHAPE[1] for u in uuids], bool)
            score = hit.astype(np.float32)
        else:
            score = (M @ np.stack([embed.embed_query(t) for t in k["words"]]).T).max(1) - base
            hit = score >= k["cut"]
        hit &= photo & ~taken
        taken |= hit
        out[kind] = [uuids[i] for i in sorted(np.where(hit)[0], key=lambda i: -score[i])]
    _found = (M, out)
    return out


def state():
    st = cleanup_state()
    return dict(clutter_not=st.get("clutter_not", []), clutter_sent=st.get("clutter_sent", {})), st


def clutter(con, kind=None, offset=0, limit=60):
    """Every kind with its count and a few covers; with kind, a page of its photos."""
    cs, _ = state()
    nope = set(cs["clutter_not"])
    f = {k: [u for u in us if u not in nope] for k, us in found(con).items()}
    kinds = [dict(kind=k, name=KINDS[k]["name"], few=KINDS[k]["few"], album=KINDS[k]["album"], n=len(f[k]),
                  sent=len(set(cs["clutter_sent"].get(k, [])) & set(f[k])), covers=f[k][:3]) for k in KINDS]
    if kind is None:
        return dict(kinds=kinds)
    if kind not in KINDS:
        raise LookupError(f"no kind {kind!r}")
    page = f[kind][offset:offset + limit]
    info, sent = photo_info(con, page), set(cs["clutter_sent"].get(kind, []))
    return dict(kinds=kinds, kind=kind, total=len(f[kind]),
                photos=[dict(info[u], sent=u in sent) for u in page if u in info])


def clutter_choose(con, body):
    """{"action": "not" | "is", "uuid"}: this photo isn't clutter (stop suggesting it), or it is after all."""
    cs, st = state()
    u = str(body.get("uuid") or "")[:64]
    if body.get("action") not in ("not", "is") or not u:
        raise ValueError("action is not or is, with a uuid")
    nope = set(cs["clutter_not"])
    st["clutter_not"] = sorted(nope | {u} if body["action"] == "not" else nope - {u})
    CLEANUP.write_text(json.dumps(st))
    return {}


def clutter_send(con, kind):
    """This kind's photos that aren't in its album yet go there, in Photos (only adding)."""
    if kind not in KINDS:
        raise LookupError(f"no kind {kind!r}")
    cs, _ = state()
    nope, sent = set(cs["clutter_not"]), set(cs["clutter_sent"].get(kind, []))
    todo = [u for u in found(con)[kind] if u not in nope and u not in sent]
    n = photos_app.add_to_photos_album(KINDS[kind]["album"], todo)
    _, st = state()
    st.setdefault("clutter_sent", {})[kind] = sorted(set(st.get("clutter_sent", {}).get(kind, [])) | set(todo))
    CLEANUP.write_text(json.dumps(st))
    return dict(added=n, album=KINDS[kind]["album"])
