"""✨ smart search's second step: Jev checks a search's first photos. Jev reads text, not pixels, so each photo is
described in words (when it was taken, Photos' labels, what the search model sees, how many named people, how bright
and colourful it is), all in one call, and its yes/no nudges the order. Never sent: the photo, names, places, or
words read from the photo (text.py)."""
import json, urllib.request
from datetime import datetime

import numpy as np
from PIL import Image, ImageFilter

from . import smartbox
from .config import THUMBS
from .store import vectors
from .why import vocab

# Judged blind (FINDINGS.md → Checking the first results with Jev): on 16 of the weakest searches the first 10s held
# 136 fitting photos of 160, not 121; on 20 everyday searches 8 got better and 2 worse. 0.02 to 0.08 did about as well.
CHECK_N, CHECK_W = 40, 0.04
_looks, _asked = {}, {}


def looks(uuid):
    """How the thumbnail looks, in words: brightness, colour and detail."""
    if uuid not in _looks:
        im = Image.open(THUMBS / f"{uuid}.jpg").convert("RGB"); im.thumbnail((256, 256))
        hsv = np.asarray(im.convert("HSV"), np.float32) / 255
        bright, sat = float(hsv[..., 2].mean()), float(hsv[..., 1].mean())
        edges = float(np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), np.float32).std()) / 255
        tone = "very dark" if bright < .15 else "dark" if bright < .3 else "bright" if bright > .7 else "medium brightness"
        colour = "black and white or nearly no colour" if sat < .06 else "muted colours" if sat < .2 else "colourful"
        detail = "blurry or plain, little detail" if edges < .06 else "some detail" if edges < .12 else "sharp, lots of detail"
        _looks[uuid] = f"{tone} ({bright:.2f}), {colour} ({sat:.2f}), {detail}"
    return _looks[uuid]


def describe(con, uuids):
    """Each photo in words, for Jev."""
    _, M, pos = vectors(con)
    ws, V = vocab(con)
    near = np.argsort(-(M[[pos[u] for u in uuids]] @ V.T), axis=1)[:, :6] if ws else [[] for _ in uuids]  # what it sees (why.py)
    out = []
    for u, idx in zip(uuids, near):
        date, labels, persons, flags = con.execute("select date, labels, persons, flags from photos where uuid=?", (u,)).fetchone()
        d, flags = datetime.fromisoformat(date), json.loads(flags or "[]")
        out.append(f"Taken {d:%B} at {d:%-I:%M %p}. Apple Photos labels: {', '.join(json.loads(labels or '[]')[:12]) or 'none'}. "
                   f"The search model sees: {', '.join(ws[i] for i in idx)}. Named people in it: {len(json.loads(persons or '[]'))}. "
                   f"Image: {looks(u)}." + (f" Flags: {', '.join(flags)}." if flags else ""))
    return out


def ask(query, descriptions):
    """[how likely each photo is a good result], in one call."""
    state = "Photos from a family library:\n" + "\n".join(f"Photo {i + 1}: {d}" for i, d in enumerate(descriptions))
    qs = {f"p{i + 1}": {"type": "noul", "instructions": f'Is photo {i + 1} likely a good result for the photo search "{query}"?'}
          for i in range(len(descriptions))}
    req = urllib.request.Request(smartbox.JEV_URL, method="POST", data=json.dumps(dict(model="jev-latest", state=state, questions=qs)).encode(),
                                 headers={"Authorization": f"Bearer {smartbox.jev_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as r:
        a = json.load(r)["answers"]
    return [float(a[f"p{i + 1}"]["noul"]) for i in range(len(descriptions))]


def check(con, query, results):
    """results, with the first CHECK_N photos reordered by score + CHECK_W × Jev's yes. Unchanged if Jev can't answer
    (no key, offline, slow): search works without it. Videos keep their place: it was measured on photos."""
    if not smartbox.jev_key() or not query.strip():
        return results, False
    head = results[:CHECK_N]
    photos = [r for r in head if r.get("kind") == "photo"]
    if not photos:
        return results, False
    _, masked = smartbox.mask(con, query)
    key = (masked, tuple(r["uuid"] for r in photos))
    if key not in _asked:
        try:
            _asked[key] = ask(masked, describe(con, list(key[1])))
        except Exception:
            return results, False
        if len(_asked) > 256:
            _asked.pop(next(iter(_asked)))
    yes = dict(zip(key[1], _asked[key]))
    head = sorted(head, key=lambda r: -(r["score"] + CHECK_W * yes.get(r["uuid"], 0.0)))
    return head + results[CHECK_N:], True
