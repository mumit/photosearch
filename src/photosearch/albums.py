"""Smart albums: a saved search that keeps itself up to date, and learns from what you take out."""
import json, re
from datetime import date, datetime

import numpy as np

from . import embed, photos_app
from .config import DATA, DIM
from .store import photo_info, vectors
from .search import EXCLUDE_W, SEASONS, filtered, interest
from .stories import slug

ALBUMS = DATA / "albums"
FILTER_KEYS = ("person", "place", "after", "before", "season", "kind")

def album_filters(a):
    f = a.get("filters") or {}
    return dict(person=[x.strip() for x in (f.get("person") or "").split(",") if x.strip()], place=f.get("place") or None,
                after=f.get("after") or None, before=f.get("before") or None, kind=f.get("kind") or None,
                months=SEASONS.get(f.get("season") or ""))


def album_vector(con, a):
    """What the album looks for: its words (minus what it should leave out), nudged towards the photos pinned into it
    and away from the ones taken out, so every removal teaches it. None for an album of filters only."""
    _, M, pos = vectors(con)
    pinned = [M[pos[u]] for u in a.get("pinned", []) if u in pos]
    removed = [M[pos[u]] for u in a.get("removed", []) if u in pos]
    if not a.get("q") and not pinned:
        return None
    v = np.zeros(DIM, np.float32)
    if a.get("q"):
        v = embed.embed_query(a["q"])
        for x in a.get("exclude") or []:
            v = v - EXCLUDE_W * embed.embed_query(x)
        v = v / np.linalg.norm(v)
    if pinned:
        v = v + 0.5 * np.mean(pinned, 0)
    if removed:
        v = v - 0.3 * np.mean(removed, 0)
    return (v / np.linalg.norm(v)).astype(np.float32)


def album_rank(con, a, k=400):
    """The candidates, best first, with scores: (uuid, score). Taken-out photos never appear."""
    keep, M = filtered(con, **album_filters(a))
    out = set(a.get("removed", []))
    v = album_vector(con, a)
    if v is None:  # filters only (a person, a place): all of them, most interesting first
        _, _, pos = vectors(con)
        score = interest(con)
        return [(u, float(score[pos[u]])) for u in sorted(keep, key=lambda u: -score[pos[u]]) if u not in out][:k]
    s = M @ v
    return [(keep[i], float(s[i])) for i in np.argsort(-s) if keep[i] not in out][:k]


def album_members(con, a):
    """Everything that scores at least the album's threshold, plus what's pinned: new photos that match join by
    themselves. An album of filters only holds every photo that passes them."""
    ranked = album_rank(con, a, k=100000)
    t, scored = a.get("threshold"), album_vector(con, a) is not None
    ids = [u for u, sc in ranked if not scored or t is None or sc >= t]
    have, out = set(ids), set(a.get("removed", []))
    return ids + [u for u in a.get("pinned", []) if u not in have and u not in out]


def load_album(aid):
    f = ALBUMS / f"{aid}.json"
    if not re.fullmatch(r"[a-z0-9-]{1,60}", aid or "") or not f.exists():
        raise LookupError(f"no album {aid!r}")
    return json.loads(f.read_text())


def albums(con):
    out = []
    for f in sorted(ALBUMS.glob("*.json"), key=lambda f: -f.stat().st_mtime) if ALBUMS.exists() else []:
        a = json.loads(f.read_text())
        ids = album_members(con, a)
        synced = a.get("photos_album", {}).get("synced")
        out.append(dict(id=a["id"], name=a["name"], q=a.get("q", ""), filters=a.get("filters", {}), n=len(ids), cover=ids[0] if ids else None,
                        new=None if synced is None else len(set(ids) - set(synced))))
    return out


def album_view(con, aid):
    a = load_album(aid)
    ids = album_members(con, a)
    info = photo_info(con, ids)
    return dict(album=a, photos=[info[u] for u in ids if u in info])


def album_preview(con, a, k=400):
    """For the album page: the ranked candidates with scores, so a slider can choose where the album ends."""
    ranked = album_rank(con, a, k)
    info = photo_info(con, [u for u, _ in ranked])
    pinned = set(a.get("pinned", []))
    extra = [u for u in pinned if u not in {u for u, _ in ranked}]
    info.update(photo_info(con, extra))
    return dict(ranked=[dict(info[u], score=sc, pinned=u in pinned) for u, sc in ranked if u in info],
                pinned=[info[u] for u in extra if u in info], scored=album_vector(con, a) is not None)


def save_album(con, body):
    """Create or update an album from the page. Validates everything; the id comes from the name."""
    if not isinstance(body, dict):
        raise ValueError("expected an album")
    name = str(body.get("name") or "").strip()[:80]
    if not name:
        raise ValueError("an album needs a name")
    q = str(body.get("q") or "").strip()[:300]
    f = {k: str((body.get("filters") or {}).get(k) or "").strip()[:100] for k in FILTER_KEYS}
    if not q and not any(f.values()):
        raise ValueError("an album needs words or a filter to look for")
    clean = lambda xs: [str(u)[:64] for u in (xs or []) if re.fullmatch(r"[0-9A-Fa-f-]{8,64}", str(u))][:2000]
    if body.get("id"):  # an update: only of an album that exists (the id names its file)
        aid = load_album(str(body["id"]))["id"]
    else:
        aid = slug(name)[:50].strip("-") or "album"
    if not body.get("id"):  # a new album: don't overwrite one with the same name
        base, n = aid, 2
        while (ALBUMS / f"{aid}.json").exists():
            aid = f"{base}-{n}"; n += 1
    old = json.loads((ALBUMS / f"{aid}.json").read_text()) if (ALBUMS / f"{aid}.json").exists() else {}
    a = dict(old, id=aid, name=name, q=q, exclude=[x.strip() for x in str(body.get("exclude") or "").split(",") if x.strip()][:5],
             filters={k: v for k, v in f.items() if v}, pinned=clean(body.get("pinned")), removed=clean(body.get("removed")),
             created=old.get("created", date.today().isoformat()))
    # Where the album ends: the page sends how many to keep (n), and the threshold is that photo's score under the
    # album's current vector. Teaching moves every score, so a threshold kept from before would be meaningless.
    a["threshold"] = None
    if album_vector(con, a) is not None:
        ranked = album_rank(con, a, k=2000)
        n = body.get("n")
        if not isinstance(n, int) or n < 1:  # no choice made: the photos close to the best match
            n = min(150, max(10, sum(sc >= ranked[0][1] - 0.07 for _, sc in ranked))) if ranked else 0
        a["threshold"] = ranked[min(n, len(ranked)) - 1][1] if ranked else None
    ALBUMS.mkdir(parents=True, exist_ok=True)
    (ALBUMS / f"{aid}.json").write_text(json.dumps(a, indent=1, ensure_ascii=False))
    return dict(id=aid, n=len(album_members(con, a)))


def delete_album(aid):
    load_album(aid)
    (ALBUMS / f"{aid}.json").unlink()
    return {}


def album_to_photos(con, aid):
    """Copy the album into the Photos app (an album of the same name). Adds only what isn't there yet."""
    a = load_album(aid)
    ids = album_members(con, a)
    done = set(a.get("photos_album", {}).get("synced", []))
    n = photos_app.add_to_photos_album(a["name"], [u for u in ids if u not in done])
    a["photos_album"] = dict(name=a["name"], synced=sorted(done | set(ids)), at=datetime.now().isoformat(timespec="seconds"))
    (ALBUMS / f"{aid}.json").write_text(json.dumps(a, indent=1, ensure_ascii=False))
    return dict(added=n, total=len(ids))
