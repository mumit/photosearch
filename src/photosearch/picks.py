"""Family picks: anyone on the page (this Mac, or a phone with `serve --lan`) loves a photo under their own name, and
the photo frame and home show what the family loved. Picks live in this index, not in Photos."""
from datetime import datetime

from .store import photo_info

WHO_MAX = 24  # a first name or a nickname


def name(who):
    who = " ".join(str(who or "").split())[:WHO_MAX]
    if not who:
        raise ValueError("say who's picking")
    return who


def pick(con, uuid, who, on=True):
    """Love (or stop loving) a photo as who. Returns who loves it now."""
    who = name(who)
    if not con.execute("select 1 from photos where uuid=?", (uuid,)).fetchone():
        raise LookupError(f"{uuid} not indexed")
    if on:
        con.execute("insert or ignore into picks values(?,?,?)", (uuid, who, datetime.now().isoformat()))
    else:
        con.execute("delete from picks where uuid=? and who=?", (uuid, who))
    con.commit()
    return loved_by(con, uuid)


def loved_by(con, uuid):
    return [w for (w,) in con.execute("select who from picks where uuid=? order by at", (uuid,))]


def picks(con, who=None):
    """{photos: the loved photos, most loved then newest pick first, each with `by`; people: [{who, n}]}."""
    rows = con.execute("select uuid, who, at from picks" + (" where who=?" if who else "") + " order by at",
                       (who,) if who else ()).fetchall()
    by, last = {}, {}
    for u, w, at in rows:
        by.setdefault(u, []).append(w); last[u] = at
    info = photo_info(con, list(by))
    order = sorted((u for u in by if u in info), key=lambda u: (len(by[u]), last[u]), reverse=True)
    people = con.execute("select who, count(*) from picks group by who order by count(*) desc, who").fetchall()
    return dict(photos=[dict(info[u], by=by[u]) for u in order], people=[dict(who=w, n=n) for w, n in people])
