"""Recreate this: old photos of someone worth shooting again, and the new shot once it's in Photos.

Ideas are photos at least AGE years old with one or two named people, ranked by how much they look like a pose (POSE).
Set by eye on a 16,000-photo library: POSE found kid portraits and a parent holding a baby, the classic shots to redo;
the general interest score (search.INTERESTING) found busy scenes, kids on a trampoline, a party, which can't be redone.

You pick the ones you'll try. A newer photo of the same person (or of nobody named yet, as Photos names faces later)
that looks as alike as MATCH_AT is offered as the new shot, and you say yes or no. The picks live in this index, never
in Photos.
"""
import json
from datetime import datetime

import numpy as np

from . import embed
from .clutter import found as clutter_found
from .store import DATED, photo_info, vectors

AGE = 5  # years
MAX_NAMED = 2
POSE = ["a child posing for the camera", "a portrait of a smiling child", "a toddler sitting in a funny pose",
        "a child standing in front of a landmark", "a parent holding a baby, posing for a photo", "a child in a costume"]
MATCH_AT = 0.80
_ideas = (None, None)


def ideas(con, offset=0, limit=24):
    """Old photos worth shooting again, one a day, best first, without the ones picked already."""
    global _ideas
    _, M, pos = vectors(con)
    if _ideas[0] is not M:
        junk = {u for v in clutter_found(con).values() for u in v}
        old = f"{datetime.now().year - AGE}"
        rows = [r for r in con.execute(f"select uuid, date, persons from photos where kind='photo' and persons!='[]' "
                                       f"and date < ? and {DATED}", (old,))
                if r[0] in pos and r[0] not in junk and len(json.loads(r[2])) <= MAX_NAMED]
        out = []
        if rows:
            P = np.stack([embed.embed_query(t) for t in POSE])
            score = (M[[pos[r[0]] for r in rows]] @ P.T).max(1)
            days = set()
            for i in np.argsort(-score):
                if rows[i][1][:10] not in days:
                    days.add(rows[i][1][:10]); out.append((rows[i][0], json.loads(rows[i][2])[0]))
        _ideas = (M, out)
    picked = {r[0] for r in con.execute("select uuid from recreate")}
    page = [x for x in _ideas[1] if x[0] not in picked][offset:offset + limit]
    info = photo_info(con, [u for u, _ in page])
    return [dict(info[u], who=who) for u, who in page]


def pick(con, uuid, person=None):
    if not con.execute("select 1 from photos where uuid=?", (uuid,)).fetchone():
        raise LookupError(uuid)
    if person is None:
        person = (json.loads(con.execute("select persons from photos where uuid=?", (uuid,)).fetchone()[0]) or [None])[0]
    con.execute("insert or ignore into recreate values(?,?,?,?,?,?)", (uuid, person, datetime.now().isoformat(), "todo", None, "[]"))
    con.commit()


def unpick(con, uuid):
    con.execute("delete from recreate where uuid=?", (uuid,)); con.commit()


def new_shot(con, uuid, person, picked, no):
    """The best newer photo of the same person (or of nobody named yet) that looks like this one, if any."""
    _, M, pos = vectors(con)
    if uuid not in pos:
        return None
    rows = [r for r in con.execute("select uuid, persons from photos where kind='photo' and date >= ?", (picked[:10],))
            if r[0] in pos and r[0] != uuid and r[0] not in no]
    rows = [u for u, p in rows if person in json.loads(p) or p == "[]"]
    if not rows:
        return None
    s = M[[pos[u] for u in rows]] @ M[pos[uuid]]
    i = int(np.argmax(s))
    return (rows[i], float(s[i])) if s[i] >= MATCH_AT else None


def recreations(con):
    """{todo: [the old photo, who, and maybe a new shot to confirm], done: [then, now, who, years]}."""
    todo, done = [], []
    rows = con.execute("select uuid, person, picked, state, match, no from recreate order by picked desc").fetchall()
    found = {}
    for u, who, picked, state, match, no in rows:
        if state == "todo" and (m := new_shot(con, u, who, picked, set(json.loads(no)))):
            found[u] = m
    info = photo_info(con, [r[0] for r in rows] + [r[4] for r in rows if r[4]] + [m[0] for m in found.values()])
    for u, who, picked, state, match, no in rows:
        if u not in info:
            continue
        if state == "done" and match in info:
            done.append(dict(then=info[u], now=info[match], who=who,
                             years=int(info[match]["date"][:4]) - int(info[u]["date"][:4])))
        elif state == "todo":
            todo.append(dict(then=info[u], who=who, **({"shot": info[found[u][0]]} if u in found else {})))
    return dict(todo=todo, done=done)


def answer(con, uuid, match, yes):
    """Yes: match is the new shot of uuid. No: it isn't, so it's not offered again."""
    row = con.execute("select no from recreate where uuid=?", (uuid,)).fetchone()
    if not row:
        raise LookupError(uuid)
    if yes:
        con.execute("update recreate set state='done', match=? where uuid=?", (match, uuid))
    else:
        con.execute("update recreate set no=? where uuid=?", (json.dumps(json.loads(row[0]) + [match]), uuid))
    con.commit()


def undo_done(con, uuid):
    con.execute("update recreate set state='todo', match=null where uuid=?", (uuid,)); con.commit()


def post(con, b):
    """The page's writes: {uuid, action: pick | unpick | yes | no | undo, match}."""
    u, a = str(b.get("uuid", "")), b.get("action")
    if a == "pick":
        pick(con, u)
    elif a == "unpick":
        unpick(con, u)
    elif a in ("yes", "no"):
        answer(con, u, str(b.get("match", "")), a == "yes")
    elif a == "undo":
        undo_done(con, u)
    else:
        raise ValueError(f"unknown action {a!r}")
    return recreations(con)
