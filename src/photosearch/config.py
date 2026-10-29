"""Where things live, and sizes. PHOTOSEARCH_DATA moves the data folder (the tests use it)."""
import os
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]  # src/photosearch/config.py
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "photosearch"
# Your own data/ and .env: in a git checkout, at its top, as always; installed (pip, uv tool), in Application
# Support, so an upgrade, which replaces the package's folder, never takes the index with it.
ROOT = CHECKOUT if (CHECKOUT / "pyproject.toml").exists() else APP_SUPPORT
WEB = Path(__file__).resolve().parent / "web"  # the page and its scripts, re-read on every request
DATA = Path(os.environ.get("PHOTOSEARCH_DATA") or ROOT / "data")
DB = DATA / "index.sqlite"
THUMBS = DATA / "thumbs"
MODEL = "google/embeddinggemma-2"
DIM = 768
THUMB_PX = 512     # grid tiles and cards are ~250 px wide, so this is sharp on a Retina screen
LARGE = DATA / "large"  # full-size copies fetched from iCloud, for photos whose local preview is tiny
DISPLAY_PX = 2560  # the most a full-screen view needs
SHARP_PX = 1600    # local previews smaller than this get fetched from iCloud when shown big
LIBRARY = Path.home() / "Pictures" / "Photos Library.photoslibrary"  # fallback if the system library can't be found
