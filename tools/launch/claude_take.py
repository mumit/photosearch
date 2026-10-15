"""Records the Claude half of the launch video: Claude Code making an album from the demo library, then a few seconds
of the Photos window showing it.

    PHOTOSEARCH_DATA=data-demo uv run python tools/launch/claude_take.py [--wait 285]

Writes data-demo/launch/claude-take.mp4 (the terminal, by VHS), photos-album.mov (only the Photos window, never the
screen) and album.json (the photos Claude chose, for check_take.py). Photos must have the demo library open and no
album called "Best hikes" yet. Claude runs from ~/.claude-demo (log in there once: `CLAUDE_CONFIG_DIR=~/.claude-demo
claude`) with only the demo's MCP server.

Nothing else may talk to Photos during the take: two scripts driving Photos at once can stall it for minutes.
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

from common import ALBUM, OUT, PROMPT, album_ids, demo_only, photos
from photosearch.config import DATA, ROOT
from photosearch.store import db

HERE = Path(__file__).resolve().parent
WORK = Path("/tmp/photosearch-demo")  # where Claude runs: its banner shows this folder


def photos_window():
    """The Photos app's main window id, for recording just that window."""
    import Quartz
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerName") == "Photos" and w.get("kCGWindowLayer") == 0:
            return w["kCGWindowNumber"]
    sys.exit("can't find the Photos window: is Photos open, and not minimized?")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait", type=int, default=285, help="seconds to record after the prompt (Claude takes ~1-3 min)")
    a = ap.parse_args()
    demo_only()
    import photoscript
    some = db().execute("select uuid from photos limit 1").fetchone()[0]
    try:
        photoscript.Photo(some)
    except ValueError:
        sys.exit("Photos doesn't have the demo library open: open it holding Option, then run this again")
    if album_ids(ALBUM) is not None:
        sys.exit(f'the demo library already has an album called "{ALBUM}": delete it in Photos first')

    WORK.mkdir(exist_ok=True)
    (WORK / ".mcp-demo.json").write_text(json.dumps({"mcpServers": {"photosearch-demo": {
        "command": "uv", "args": ["run", "--quiet", "--directory", str(ROOT), "photosearch-mcp"],
        "env": {"PHOTOSEARCH_DATA": str(DATA.resolve())}}}}, indent=1))
    tape = OUT / "claude-take.tape"
    tape.write_text((HERE / "claude-take.tape").read_text().format(
        out=OUT / "claude-take.mp4", work=WORK, prompt=PROMPT, wait=a.wait))
    print(f"recording Claude ({a.wait + 20} s or so)…", flush=True)
    subprocess.run(["vhs", str(tape)], check=True, stdout=subprocess.DEVNULL)

    ids = album_ids(ALBUM)
    if not ids:
        sys.exit(f'Claude didn\'t make "{ALBUM}" (or it\'s empty): the terminal video shows what happened')
    (OUT / "album.json").write_text(json.dumps(ids))
    photos(f'spotlight album "{ALBUM}"')
    time.sleep(2)
    mov = OUT / "photos-album.mov"
    mov.unlink(missing_ok=True)
    subprocess.run(["screencapture", "-x", "-v", "-V8", f"-l{photos_window()}", str(mov)], check=True)
    print(f"wrote {OUT / 'claude-take.mp4'}, {mov.name} and album.json ({len(ids)} photos)")


if __name__ == "__main__":
    main()
