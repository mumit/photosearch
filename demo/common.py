"""What reset.py and finish.sh share: the album Claude is asked to make, asking Photos by AppleScript, and the refusal
that keeps them off your own library. Points photosearch at data-demo/, so import this before photosearch."""
import os, subprocess, sys
from pathlib import Path

PS = Path(__file__).resolve().parent.parent  # photosearch: this folder is its demo/
os.environ["PHOTOSEARCH_DATA"] = str(PS / "data-demo")  # before photosearch.config is imported

ALBUM = "Best hikes"  # what Claude is asked to make, in claude.tape


def photos(script, timeout=60):
    """Ask Photos something by AppleScript; None when it doesn't answer."""
    r = subprocess.run(["osascript", "-e", f"with timeout of {timeout} seconds", "-e", f'tell application "Photos" to {script}',
                        "-e", "end timeout"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def album_ids(name):
    """The uuids in a Photos album of the open library, or None if there's no such album."""
    if photos(f'exists album "{name}"') != "true":
        return None
    out = photos(f'get id of media items of album "{name}"') or ""
    return [i.strip().split("/")[0] for i in out.split(",") if i.strip()]


def demo_library_open():
    """Refuse unless Photos has the demo library open: a photo from the demo index must be one Photos knows."""
    import photoscript
    from photosearch.store import db
    try:
        photoscript.Photo(db().execute("select uuid from photos limit 1").fetchone()[0])
    except ValueError:
        sys.exit("Photos doesn't have the demo library open: open Photosearch Demo holding Option, then run again")
