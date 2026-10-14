"""A small made-up Photos library for the tests: an index with vectors from a fake search model, and thumbnails.

The fake model maps text to a few "concepts" (one axis each), so a photo of the beach is close to "beach" and every
test can say what it should find. The photos include traps the duplicate finder has fallen into on a real library:
different receipts, different screenshots, look-alikes years apart, and a chain of shots that drifts.
"""
import hashlib, json, sqlite3, uuid as uuidlib
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DIM = 768
AXES = dict(fun=0, doc=1, face=2, beach=3, dog=4, snow=5, cake=6, sunset=7, city=8, arcx=9, arcy=10, receipt=11, screen=12, garden=13)
WORDS = dict(beach="beach", dog="dog", snow="snow", cake="cake", birthday="cake", sunset="sunset", city="city", street="city",
             receipt="receipt", screenshot="screen")

HOME = (45.52, -122.68)  # Portland
COAST = (45.89, -123.96)
LISBON = (38.72, -9.14)
GEO = {HOME: dict(city="Portland", state="Oregon", country="USA"),
       COAST: dict(city="Cannon Beach", state="Oregon", country="USA"),
       LISBON: dict(city="Lisbon", country="Portugal")}
PLACE = {HOME: "Portland, Oregon, USA", COAST: "Cannon Beach, Oregon, USA", LISBON: "Lisbon, Portugal"}


def axis(name):
    v = np.zeros(DIM, np.float32); v[AXES[name]] = 1
    return v


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


def noise(rng, scale):
    n = rng.standard_normal(DIM).astype(np.float32); n[:20] = 0  # off the concept axes
    return scale * n / np.linalg.norm(n)


def fake_embed(text, interesting=(), boring=(), portrait=""):
    """What the real model does, roughly: text lands near the photos it describes."""
    if text in interesting:
        return axis("fun")
    if text in boring:
        return axis("doc")
    if text == portrait:
        return axis("face")
    hits = [w for w in WORDS if w in text.lower()]
    if hits:
        return unit(sum(axis(WORDS[w]) for w in hits))
    rng = np.random.default_rng(int(hashlib.md5(text.encode()).hexdigest()[:8], 16))
    return unit(noise(rng, 1))


class Library:
    def __init__(self, seed=7):
        self.rng = np.random.default_rng(seed)
        self.photos, self.named = [], {}

    def add(self, vec, when, name=None, kind="photo", where=None, persons=(), image=None, labels=()):
        u = str(uuidlib.UUID(int=int(self.rng.integers(1 << 62)) << 64 | len(self.photos))).upper()
        self.photos.append(dict(uuid=u, vec=unit(vec), date=when.isoformat(), kind=kind, where=where, persons=list(persons),
                                image=image if image is not None else self.picture(), labels=list(labels)))
        if name:
            self.named[name] = u
        return u

    def picture(self, w=400, h=300, rng=None):
        """Something photo-like and unique: smooth colour blobs with fine texture."""
        rng = rng or self.rng
        base = rng.integers(0, 255, (6, 8, 3)).astype(np.uint8)
        im = Image.fromarray(base).resize((w, h), Image.BICUBIC)
        a = np.asarray(im, np.int16) + rng.integers(-25, 25, (h, w, 1))
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    def receipt(self):
        im = Image.new("RGB", (300, 400), "white"); d = ImageDraw.Draw(im)
        for y in range(30, 380, 22):
            d.rectangle((25, y, 25 + int(self.rng.integers(60, 250)), y + 9), fill="black")
        return im

    def build(self, data):
        """Writes data/index.sqlite and data/thumbs/ as `photosearch index` would."""
        thumbs = data / "thumbs"; thumbs.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(data / "index.sqlite")
        con.execute("""create table photos(uuid text primary key, date text, kind text, title text, place text,
            persons text, albums text, labels text, src text, vec blob, lat real, lon real, geo text)""")
        con.execute("create table meta(key text primary key, value text)")
        for p in self.photos:
            f = thumbs / f"{p['uuid']}.jpg"
            p["image"].save(f, quality=90)
            lat, lon = p["where"] or (None, None)
            con.execute("insert into photos values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (p["uuid"], p["date"], p["kind"], "", PLACE.get(p["where"], ""), json.dumps(p["persons"]), "[]",
                         json.dumps(p["labels"]), str(f), p["vec"].tobytes(), lat, lon, json.dumps(GEO.get(p["where"], {}))))
        con.commit(); con.close()


def build(data):
    """The test library. Returns {name: uuid} for the photos tests refer to."""
    L = Library()
    rng = L.rng
    fun = lambda concept, n=0.5: 0.6 * axis("fun") + rng.uniform(0.7, 1.3) * axis(concept) + noise(rng, n)
    for i in range(8):  # summers at the beach, with Sam (and sometimes Alex)
        L.add(fun("beach"), datetime(2018 + i, 7, 10 + i, 14), f"beach{i}", where=COAST,
              persons=[["Sam"], ["Sam", "Alex"], []][i % 3], labels=["Beach", "Ocean"])
    for i in range(8):  # the dog, at home
        L.add(fun("dog"), datetime(2019 + i % 6, 1 + i, 5, 10), f"dog{i}", where=HOME, persons=["Alex"] if i % 2 else [],
              labels=["Dog", "Animal"])
    for i in range(6):
        L.add(fun("snow"), datetime(2019 + i, 1, 20, 11), f"snow{i}", where=HOME, labels=["Snow"])
    for i in range(5):  # birthdays
        L.add(fun("cake"), datetime(2020 + i, 9, 3, 18), f"cake{i}", where=HOME, persons=["Sam"], labels=["Cake"])
    for i in range(22):  # a trip: 22 photos over five days in Lisbon
        L.add(fun("city"), datetime(2025, 3, 10 + i // 5, 9 + 2 * (i % 5)), f"lisbon{i}", where=LISBON,
              persons=[["Sam"], ["Alex"], ["Sam", "Alex"], []][i % 4], labels=["City", "Street"])
    for i in range(6):  # 2025 at home, so the trip stands out as away
        L.add(fun("garden"), datetime(2025, 4 + i, 12, 16), f"garden{i}", where=HOME)
    L.add(fun("dog"), datetime(2024, 6, 1, 9), "video", kind="video", where=HOME)
    L.add(0.6 * axis("fun") + axis("face") + noise(rng, 0.3), datetime(2025, 5, 5, 12), "portrait", where=HOME, persons=["Sam"])

    # A burst: three near-identical shots seconds apart. The first is the sharpest.
    v, pic = fun("sunset"), L.picture()
    for k, blur in enumerate((0, 2.5, 1.2)):
        L.add(v + noise(rng, 0.02), datetime(2024, 5, 1, 20, 0, 3 * k), f"burst{k}", where=HOME,
              image=pic.filter(ImageFilter.GaussianBlur(blur)) if blur else pic)
    # The same picture imported twice, years apart.
    v, pic = fun("beach"), L.picture()
    L.add(v, datetime(2021, 6, 1, 12), "copy0", image=pic); L.add(v, datetime(2023, 2, 10, 8), "copy1", image=pic.copy())
    # Look alike to the model, years apart, but different pictures: not copies.
    v = fun("snow")
    L.add(v, datetime(2020, 8, 1, 12), "alike0"); L.add(v + noise(rng, 0.05), datetime(2022, 8, 1, 12), "alike1")
    # Two different receipts, 30 s apart: the model sees every receipt as the same picture.
    v = axis("doc") + 0.8 * axis("receipt")
    L.add(v + noise(rng, 0.05), datetime(2024, 2, 2, 10), "receipt0", image=L.receipt())
    L.add(v + noise(rng, 0.05), datetime(2024, 2, 2, 10, 0, 30), "receipt1", image=L.receipt())
    # The same receipt photographed twice: that is a duplicate.
    pic = L.receipt()
    L.add(v + noise(rng, 0.3), datetime(2023, 11, 11, 9), "receiptcopy0", image=pic)
    L.add(L.photos[-1]["vec"], datetime(2023, 11, 11, 9, 0, 20), "receiptcopy1", image=pic.copy())
    # Two colourful phone screenshots (tall), 15 s apart, different screens.
    v = 0.6 * axis("fun") + axis("screen")
    for k in range(2):
        L.add(v + noise(rng, 0.03), datetime(2024, 3, 3, 21, 0, 15 * k), f"screen{k}", image=L.picture(184, 400))
    # A chain: each shot is like the next (0.975), but the last isn't like the first (0.90). No group may hold both.
    for k in range(3):
        t = np.radians(14.4 * k)
        L.add(0.5 * axis("fun") + np.cos(t) * axis("arcx") + np.sin(t) * axis("arcy"), datetime(2022, 4, 4, 15, k), f"chain{k}",
              where=HOME)
    L.build(data)
    return L.named
