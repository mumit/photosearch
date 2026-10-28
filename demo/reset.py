"""Gets the demo ready for a take: refuses unless Photos has the demo library open, deletes the "Best hikes" album
the last take made (an album only, never photos), and writes the MCP config Claude uses in its work folder.

    uv run --project .. python reset.py
"""
import json
from pathlib import Path

from common import ALBUM, PS, album_ids, demo_library_open, photos
from photosearch.config import DATA

WORK = Path("/tmp/photosearch-demo")  # where Claude runs: its banner shows this folder
# Claude Code shows "Updated to latest" once after an update; the demo's own config folder mustn't show it on camera
UPDATED = Path.home() / ".claude-demo" / ".last-update-result.json"


def main():
    demo_library_open()
    if album_ids(ALBUM) is not None:
        if photos(f'delete album "{ALBUM}"') is None or album_ids(ALBUM) is not None:
            raise SystemExit(f'couldn\'t delete the demo library\'s "{ALBUM}" album: delete it in Photos, then run again')
        print(f'deleted the last take\'s "{ALBUM}" album from the demo library')
    UPDATED.unlink(missing_ok=True)
    WORK.mkdir(exist_ok=True)
    (WORK / ".mcp-demo.json").write_text(json.dumps({"mcpServers": {"photosearch-demo": {
        "command": "uv", "args": ["run", "--quiet", "--directory", str(PS), "photosearch-mcp"],
        "env": {"PHOTOSEARCH_DATA": str(DATA.resolve())}}}}, indent=1))
    print(f"ready: demo library open, no \"{ALBUM}\" album, MCP config in {WORK}")


if __name__ == "__main__":
    main()
