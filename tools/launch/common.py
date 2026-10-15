"""What the launch tools share: where their files go, and the refusals that keep them off your own library."""
import json, subprocess, sys

from photosearch.config import DATA, ROOT

OUT = DATA / "launch"  # recordings, review sheets, the list of photos checked, the finished cuts: inside the demo's data
ALBUM = "Best hikes"   # what Claude is asked to make
PROMPT = (f'Make an album called "{ALBUM}" from my photos: trails, forests and views from the top. No people, nothing '
          "blurry, so look at them before you add any.")
REMOVE = "Remove from demo"  # where photos that fail a check are put, for you to delete in Photos


def demo_only():
    """Refuse to run on your own library's data folder: these tools record and publish what they find."""
    if DATA.resolve() == (ROOT / "data").resolve():
        sys.exit("run with PHOTOSEARCH_DATA pointing at the demo's data folder, e.g. PHOTOSEARCH_DATA=data-demo")
    OUT.mkdir(parents=True, exist_ok=True)


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


def load(name, default):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else default
