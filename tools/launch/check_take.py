"""Every photo a take could show, checked by eye before anything is shared: the ones the director's takes loaded,
the ones Claude put in its album, and Rediscover's whole pool (the home page picks from it at random, so each take
shows a few different ones).

    PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py            # sheets of what's not checked yet
    PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py remove 3-2 7-1   # these fail: off to Photos
    PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py ok         # the rest of the sheets passed

Sheets go to data-demo/launch/review/, four photos each, labelled like 3-2. Look at every one at full size for anyone
at all (faces, heads at the edges, tiny figures, reflections in glass, people in boats) and anything that identifies
(plates, house numbers, documents, screens); when in doubt, it fails. `remove` puts photos in the "Remove from demo"
album; delete them in Photos (and empty Recently Deleted), re-index, and take again. `ok` records every other photo on
the sheets as checked, in data-demo/launch/checked.json, so later takes only show what's new.
"""
import json, sys
from datetime import date

from common import OUT, REMOVE, demo_only, load
from photosearch import photos_app
from photosearch.explore import rediscover_pool
from photosearch.store import db

REVIEW = OUT / "review"


def candidates(con):
    """Every photo that may be in the video, if it's still in the demo library."""
    want = set(rediscover_pool(con)) | set(load("album.json", []))
    for f in OUT.glob("*.photos.json"):
        want |= set(json.loads(f.read_text()))
    have = {r[0] for r in con.execute("select uuid from photos")}
    return sorted(want & have)


def sheets(con, uuids):
    """Numbered sheets of the photos at full size, four at a time; returns {label: uuid}."""
    from PIL import Image, ImageDraw
    from photosearch.images import open_image
    for old in [*REVIEW.glob("*.jpg"), REVIEW / "failed.json"]:
        old.unlink(missing_ok=True)
    REVIEW.mkdir(exist_ok=True)
    key = {}
    for s in range(0, len(uuids), 4):
        sheet = Image.new("RGB", (2 * 1010, 2 * 790), "white")
        d = ImageDraw.Draw(sheet)
        for j, u in enumerate(uuids[s:s + 4]):
            src = con.execute("select src from photos where uuid=?", (u,)).fetchone()[0]
            im = open_image(src, 1000)
            im.thumbnail((1000, 750))
            x, y, label = (j % 2) * 1010, (j // 2) * 790, f"{s // 4 + 1}-{j + 1}"
            sheet.paste(im, (x, y + 34))
            d.rectangle((x, y, x + 70, y + 30), fill="black")
            d.text((x + 8, y + 8), label, fill="white")
            key[label] = u
        sheet.save(REVIEW / f"{s // 4 + 1:02}.jpg", quality=92)
    (REVIEW / "key.json").write_text(json.dumps(key, indent=1))
    return key


def main():
    demo_only()
    con, checked = db(), load("checked.json", {})
    args = sys.argv[1:]
    if args[:1] == ["remove"]:
        key = load("review/key.json", {})
        uuids = [key[l] for l in args[1:]]
        n = photos_app.add_to_photos_album(REMOVE, uuids)
        (REVIEW / "failed.json").write_text(json.dumps(sorted(set(load("review/failed.json", [])) | set(uuids))))
        print(f'put {n} in "{REMOVE}". In Photos: open it, select all, delete, empty Recently Deleted, delete the '
              "album; then re-index (photosearch index) and take again")
    elif args[:1] == ["ok"]:
        key, failed = load("review/key.json", {}), set(load("review/failed.json", []))
        passed = [u for u in key.values() if u not in failed]
        checked |= {u: date.today().isoformat() for u in passed}
        (OUT / "checked.json").write_text(json.dumps(checked, indent=1, sort_keys=True))
        print(f"{len(passed)} more checked ({len(checked)} in all); {len(failed)} failed, to delete in Photos")
    else:
        todo = [u for u in candidates(con) if u not in checked]
        if not todo:
            sys.exit(print("✓ every photo these takes can show has been checked") or 0)
        key = sheets(con, todo)
        print(f"{len(todo)} photos not checked yet, on {(len(todo) + 3) // 4} sheets in {REVIEW}")
        sys.exit(1)


if __name__ == "__main__":
    main()
