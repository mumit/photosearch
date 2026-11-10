"""`photosearch index --quick`, then a plain `index` redoing the quick vectors at full quality, newest first. With a
stand-in Photos library (three new photos) and a stand-in model whose vectors say how many vision tokens made them."""
from argparse import Namespace
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from photosearch import config, index
from library import unit, noise


class Model:
    """Each image's vector, from its pixels; at 70 tokens, nudged the way the real model's are."""
    def __init__(self):
        self.tokens, self.calls = 280, []
        self.proc = SimpleNamespace(image_processor=SimpleNamespace())

    def __getitem__(self, i):
        return SimpleNamespace(processor=self.proc)

    def encode(self, items, **kw):
        self.tokens = self.proc.image_seq_length
        self.calls.append(self.tokens)
        return np.stack([self.vec(it["image"], self.tokens) for it in items])

    @staticmethod
    def vec(im, tokens):
        rng = np.random.default_rng(int(np.asarray(im).sum()) % 2**32)
        v = unit(noise(rng, 1))
        return unit(v + 0.05 * noise(np.random.default_rng(1), 1)) if tokens == 70 else v


@pytest.fixture
def photos(lib, monkeypatch):
    """Three photos new to the index, a day apart, newest last; and the model they meet."""
    src = sorted(config.THUMBS.glob("*.jpg"))[:3]
    ps = [SimpleNamespace(uuid=f"NEW-{i}", date=datetime(2026, 1, 1 + i, tzinfo=timezone.utc), ismovie=False, isphoto=True,
                          title="", place=None, persons=[], albums=[], labels=[], location=None, path_derivatives=[str(f)],
                          path=None, screenshot=False, selfie=False) for i, f in enumerate(src)]
    old = {u for (u,) in index.db().execute("select uuid from photos")}
    pdb = SimpleNamespace(library_path=str(config.DATA), photos=lambda intrash=False: ps + [SimpleNamespace(uuid=u) for u in old])
    monkeypatch.setattr(index, "photos_db", lambda library=None: pdb)
    monkeypatch.setattr(index, "meta", lambda p: ("" if not hasattr(p, "date") else p.date.isoformat(), "photo", "", "", "[]",
                                                  "[]", "[]", None, None, "{}", "[]", "{}"))
    m = Model()
    monkeypatch.setattr(index.embed, "model", lambda audio=False: m)
    return ps, m


def run(**kw):
    index.cmd_index(Namespace(**dict(dict(library=None, limit=None, batch=2, no_videos=True, quick=False), **kw)))


def new_rows(con):
    return {u: (np.frombuffer(v, np.float32), q) for u, v, q in con.execute("select uuid, vec, quick from photos where uuid like 'NEW-%'")}


def test_quick_then_full(con, photos):
    ps, m = photos
    run(quick=True)
    rows = new_rows(con)
    assert {u: q for u, (_, q) in rows.items()} == {p.uuid: 1 for p in ps} and m.calls == [70, 70]
    assert m.proc.image_seq_length == 280  # back to the full setting afterwards
    shift = index.quick_shift()
    im = index.open_image(ps[0].path_derivatives[0])
    assert np.allclose(rows["NEW-0"][0], Model.vec(im, 70) - shift)  # moved back along the words' direction

    m.calls.clear(); run(limit=1)  # the newest first
    rows = new_rows(con)
    assert m.calls == [280] and rows["NEW-2"][1] is None and rows["NEW-0"][1] == 1
    run()
    rows = new_rows(con)
    assert all(q is None for _, q in rows.values()) and np.allclose(rows["NEW-0"][0], Model.vec(im, 280))
    m.calls.clear(); run()
    assert m.calls == []  # nothing left to redo


def test_a_photo_it_cant_read_is_kept_track_of(con, photos):
    from photosearch import store
    ps, m = photos
    m.proc.image_seq_length = 280
    ps[0].path_derivatives = []  # only in iCloud
    run(limit=3)
    assert con.execute("select uuid, reason from skipped").fetchall() == [("NEW-0", "no preview on this Mac")]
    gaps = {g["gap"]: g for g in store.coverage(con)["gaps"]}
    assert gaps["not indexed"]["n"] == 1 and gaps["not indexed"]["why"] == {"no preview on this Mac": 1}
    ps[0].path_derivatives = [ps[1].path_derivatives[0]]  # Photos downloaded it since
    run(limit=3)
    assert con.execute("select count(*) from skipped").fetchone()[0] == 0
    assert "not indexed" not in {g["gap"] for g in store.coverage(con)["gaps"]}


def test_a_quick_photo_that_loses_its_preview_is_still_indexed(con, photos):
    from photosearch import store
    ps, _ = photos
    run(quick=True)
    ps[0].path_derivatives = []  # Photos freed the preview before the full redo
    run(limit=3)
    assert con.execute("select count(*) from skipped").fetchone()[0] == 0
    assert "not indexed" not in {g["gap"] for g in store.coverage(con)["gaps"]}


def test_status_counts_what_index_hasnt_seen(con, photos, monkeypatch):
    """Photos new in Photos since the last index, and ones deleted there that search still finds, come from the library."""
    from photosearch import store
    ps, m = photos
    m.proc.image_seq_length = 280
    lib = {p.uuid for p in index.photos_db().photos()}
    monkeypatch.setattr(store, "library_uuids", lambda: set(lib))
    gaps = lambda: {g["gap"]: g["n"] for g in store.coverage(con)["gaps"]}
    assert gaps()["new in Photos since the last index"] == 3
    ps[0].path_derivatives = []  # only in iCloud: tried, and listed as not indexed instead
    run()
    assert "new in Photos since the last index" not in gaps() and gaps()["not indexed"] == 1
    lib.discard("NEW-1")  # deleted in Photos
    assert gaps()["deleted from Photos, still found by search"] == 1


def test_the_library_is_read_again_only_when_photos_changes_it(lib, tmp_path, monkeypatch):
    import os
    from photosearch import store
    (tmp_path / "database").mkdir(); f = tmp_path / "database" / "Photos.sqlite"; f.write_text("")
    reads = []

    def photos_db(library):
        reads.append(library)
        return SimpleNamespace(photos=lambda intrash=False: [SimpleNamespace(uuid=f"P{len(reads)}")])
    monkeypatch.setattr(store, "index_library", lambda: str(tmp_path))
    monkeypatch.setattr(store, "photos_db", photos_db)
    assert store.library_uuids() == {"P1"} and store.library_uuids() == {"P1"} and len(reads) == 1
    os.utime(f, ns=(1, 1))  # Photos wrote to it
    assert store.library_uuids() == {"P2"}
    monkeypatch.setattr(store, "photos_db", lambda library: 1 / 0)  # no access to Photos: no gap, not an error
    os.utime(f, ns=(2, 2))
    assert store.library_uuids() is None and "photos" in store.coverage(store.db())
