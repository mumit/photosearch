"""The command, run as its own process (as the web server runs it for fetches and Photos albums). Only commands that
never reach Photos or the model: a separate process doesn't get the tests' stand-ins."""
import os, subprocess, sys

from photosearch import config


def run(*args):
    r = subprocess.run([sys.executable, "-m", "photosearch", *args], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PHOTOSEARCH_DATA=str(config.DATA)))
    assert r.returncode == 0, r.stderr[-500:]
    return r.stdout


def test_help_lists_every_command():
    out = run("--help")
    for cmd in ("index", "search", "serve", "fetch", "add-to-album", "trips", "today", "review"):
        assert cmd in out
    assert out.startswith("usage: photosearch")


def test_trips_on_the_made_up_library():
    assert "trip-2025-03-10" in run("trips") and "Lisbon" in run("trips")



def test_tests_cant_reach_photos_or_the_model():
    import pytest
    for name in ("osxphotos", "torch", "sentence_transformers"):
        with pytest.raises(ImportError, match="stand-ins"):
            __import__(name)
