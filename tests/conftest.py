"""Every test runs against a fresh copy of a made-up library (tests/library.py), with a fake search model, and with
everything that would touch the Photos app or iCloud replaced: nothing here reads or writes the real library."""
import os, shutil, sys, tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="photosearch-test-"))
os.environ["PHOTOSEARCH_DATA"] = str(WORK / "data")  # before ps is imported: all its paths hang off this
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import ps  # noqa: E402
import library  # noqa: E402

TEMPLATE = WORK / "template"
NAMED = library.build(TEMPLATE)


def fake_embed(text):
    return library.fake_embed(text, ps.INTERESTING, ps.BORING, ps.PORTRAIT)


def reset_caches():
    ps._vecs = (None, [], np.zeros((0, ps.DIM), np.float32), {})
    ps._interest = (None, None)
    for c in (ps._dupes, ps._sharp, ps._hash, ps._px, ps._ar):
        c.clear()


class PhotosApp:
    """Stands in for the Photos app: records what would have been added to which album."""
    def __init__(self):
        self.added = []

    def __call__(self, name, uuids):
        uuids = list(dict.fromkeys(uuids))
        self.added.append((name, uuids))
        return len(uuids)


def no_photos_app(name, uuids):
    raise AssertionError("a test reached the real Photos app")


@pytest.fixture(scope="session", autouse=True)
def offline():
    """For the whole run: the fake model, and no Photos app, iCloud or smart-search service."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ps, "embed_query", fake_embed)
        mp.setattr(ps, "model", lambda: None)
        mp.setattr(ps, "add_to_photos_album", no_photos_app)
        mp.setattr(ps, "fetch_in_subprocess", lambda con, uuids, wait=True: [])
        mp.setattr(ps, "jev_key", lambda: None)
        yield


@pytest.fixture(autouse=True)
def lib(monkeypatch):
    """{name: uuid} of the made-up library's photos, freshly copied into place."""
    shutil.rmtree(ps.DATA, ignore_errors=True)
    shutil.copytree(TEMPLATE, ps.DATA)
    reset_caches()
    monkeypatch.setattr(ps, "add_to_photos_album", PhotosApp())
    return dict(NAMED)


@pytest.fixture
def photos_app():
    return ps.add_to_photos_album


@pytest.fixture
def con():
    c = ps.db()
    yield c
    c.close()


def pytest_sessionfinish(session):
    shutil.rmtree(WORK, ignore_errors=True)
