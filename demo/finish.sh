#!/bin/sh
# Finishes a run: records the Photos window showing the album Claude made, then cuts the final video and README GIF
# with it and makes their check sheets. Versioned runs record web and VHS takes only, so this one-window take is
# separate. Leave Photos alone while it runs.
#
#     sh finish.sh RUN_ID
#
# Writes takes/final/RUN_ID-TIME/: photos-album.mov, album.json, photosearch.mp4, photosearch-readme.gif,
# photosearch.srt and review/.
set -eu
cd "$(dirname "$0")"
PHOTOSEARCH_DIR=$(cd .. && pwd)
run=takes/runs/${1:?usage: sh finish.sh RUN_ID}
for f in "$run/takes/web.mp4" "$run/takes/claude.mp4"; do
  [ -f "$f" ] || { echo "missing $f: is $1 a finished run?" >&2; exit 1; }
done
out=takes/final/$1-$(date +%Y%m%d-%H%M%S)
mkdir -p "$out"

# The album Claude made, from the demo library, shown in Photos (refuses unless the demo library is open)
uv run --quiet --project "$PHOTOSEARCH_DIR" python - "$out/album.json" <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from common import ALBUM, album_ids, demo_library_open, photos
demo_library_open()
ids = album_ids(ALBUM)
if not ids:
    sys.exit(f'no "{ALBUM}" album in the demo library: the Claude take shows what happened')
Path(sys.argv[1]).write_text(json.dumps(ids))
photos(f'spotlight album "{ALBUM}"')
print(f'"{ALBUM}": {len(ids)} photos')
EOF
sleep 2

# Only the Photos window, by its id
id=$(reshoot window --list | awk '$2 == "Photos" { print $1; exit }')
[ -n "$id" ] || { echo "no Photos window on screen (minimized?)" >&2; exit 1; }
reshoot window Photos "$out/photos-album.mov" --id "$id" -s 8

reshoot edit edit.py "$run/takes/web.mp4" "$run/takes/claude.mp4" "$out/photos-album.mov" "$out"
reshoot check "$out/photosearch.mp4" "$out/photosearch-readme.gif" "$out/photos-album.mov" \
  --full --ocr vision --text-file "$out/photosearch.srt" --review "$out/review" || code=$?
echo "final: $out"
# check exits 1 while sheets wait for a person, 2 when the check itself failed
[ "${code:-0}" -le 1 ] || exit "$code"
