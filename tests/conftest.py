"""Every test runs against a fresh copy of a made-up library (tests/library.py), with a fake search model, and with
everything that would touch the Photos app or iCloud replaced: nothing here reads or writes the real library."""
import os, shutil, sys, tempfile
from pathlib import Path

import numpy as np
import pytest

WORK = Path(tempfile.mkdtemp(prefix="photosearch-test-"))
os.environ["PHOTOSEARCH_DATA"] = str(WORK / "data")  # before photosearch is imported: all its paths hang off this


class NoPhotosOrModel:
    """The tests must pass on a fresh clone, for someone whose terminal can't read Photos and who hasn't downloaded the
    model: so the libraries that read the Photos library or run the model can't even be imported here."""
    BLOCKED = ("osxphotos", "photoscript", "photokit", "torch", "sentence_transformers", "transformers")

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"{name} reads your Photos library or runs the model; tests use the stand-ins in conftest.py")


sys.meta_path.insert(0, NoPhotosOrModel())

from photosearch import clutter, config, dupes, embed, people, search, smartbox, store  # noqa: E402
from photosearch import photos_app as photos  # noqa: E402  (the fixture below is called photos_app)
import library  # noqa: E402

TEMPLATE = WORK / "template"
NAMED = library.build(TEMPLATE)


def fake_embed(text):
    return library.fake_embed(text, search.INTERESTING, search.BORING, people.PORTRAIT)


def reset_caches():
    store._vecs = (None, [], np.zeros((0, config.DIM), np.float32), {})
    search._interest = (None, None)
    clutter._found = (None, None)
    for c in (dupes._dupes, dupes._sharp, dupes._hash, dupes._px, store._ar):
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
        mp.setattr(embed, "embed_query", fake_embed)
        mp.setattr(embed, "model", lambda: None)
        mp.setattr(photos, "add_to_photos_album", no_photos_app)
        mp.setattr(photos, "fetch_in_subprocess", lambda con, uuids, wait=True: [])
        mp.setattr(smartbox, "jev_key", lambda: None)
        yield


@pytest.fixture(autouse=True)
def lib(monkeypatch):
    """{name: uuid} of the made-up library's photos, freshly copied into place."""
    shutil.rmtree(config.DATA, ignore_errors=True)
    shutil.copytree(TEMPLATE, config.DATA)
    reset_caches()
    monkeypatch.setattr(photos, "add_to_photos_album", PhotosApp())
    return dict(NAMED)


@pytest.fixture
def photos_app():
    return photos.add_to_photos_album


@pytest.fixture
def con():
    c = store.db()
    yield c
    c.close()


def pytest_sessionfinish(session):
    shutil.rmtree(WORK, ignore_errors=True)
