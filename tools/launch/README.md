# Reshooting the launch video

The launch video is made from three takes:
- the web app acting out a storyboard;
- Claude Code making an album;
- a few seconds of the Photos window showing that album.

These run on a **separate demo Photos library**, never your own. Every photo a take can show is checked by eye before anything is cut, and nothing is shared until a person has watched the result.

Everything below runs from the repo root. Recordings, review sheets, the list of checked photos and the finished cuts all go in `data-demo/launch/`, which git ignores.

| Tool | What it does |
|---|---|
| [`tools/director/`](../director/) | Records the web app in headless Chrome from `storyboard.py`. Only the page is captured, never the screen. Next to the video it writes `.photos.json`, every photo the page loaded, and `.beats.json`, when each beat started. |
| `claude_take.py` | Records Claude Code making "Best hikes" with [VHS](https://github.com/charmbracelet/vhs), using `claude-take.tape`. Then it records only the Photos window showing the album. |
| `check_take.py` | Puts every photo the takes could show, and not yet checked, on numbered sheets. It records what passed and sends what failed to Photos for you to delete. |
| `edit.py` | Cuts the 16:9 video, a 9:16 version and one GIF per section from the takes. The words on screen are at the top of the file. |

## Once

1. **Tools:**

   ```bash
   brew install vhs ffmpeg
   ```

   You also need Google Chrome, which the director drives.
2. **A demo library.** In Photos, hold **Option** while opening it, choose **Create New…**, and import only photos you're happy for anyone to see. Trips, landscapes, animals and food work well. Then index it into its own data folder:

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run photosearch index
   ```

   The index remembers which library it came from. Adding to albums is refused unless that library is the one open in Photos.

   **Leave out:**
   - people;
   - screenshots;
   - anything from near home;
   - anything with names, plates, house numbers or documents.
3. **Claude's own config folder,** so the take shows a clean Claude Code with nothing from your usual setup. Log in once:

   ```bash
   CLAUDE_CONFIG_DIR=~/.claude-demo claude
   ```

   Use whichever account you want to appear on screen.
4. **Screen Recording permission** for your terminal: System Settings → Privacy & Security → Screen Recording. It's needed for the Photos window clip only.

## Each reshoot

1. **Open the demo library in Photos.** Hold Option while opening Photos and pick it. Delete any "Best hikes" album left over from the last take.
2. **Check the demo gives nothing of yours away.**

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run photosearch demo-check data
   ```

   It goes through everything the page can show and compares it with your own index:
   - names;
   - places near home;
   - photo ids;
   - locations.

   It also has macOS Vision look for faces and people. Fix whatever it reports before going on.
3. **Serve the demo in presenter mode.** Leave this running:

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run photosearch serve --demo --port 8766
   ```

4. **Record the web take** (about a minute):

   ```bash
   uv run python tools/director/director.py tools/director/storyboard.py data-demo/launch/web.mp4
   ```

5. **Record the Claude take** (about 5 minutes). Leave Photos alone while it runs: two scripts driving Photos at once can stall it.

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run python tools/launch/claude_take.py
   ```

6. **Check every photo the takes can show:**

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py
   ```

   This covers the web take, Claude's album and Rediscover's whole pool. Rediscover is the home page's shelf, which picks at random, so each take shows different photos. The sheets go to `data-demo/launch/review/`. Look at each photo at full size.

   **What fails a photo:**
   - anyone at all, including heads at the frame's edge, tiny distant figures, reflections in aquarium glass, and people on boats or behind windows;
   - anything that identifies a person or place: names, plates, house numbers, documents, screens.

   When in doubt, it fails. Past misses were a straw hat at the edge of a frame, a silhouette in a lookout's mesh railing, and a blurred head under a hippo.

   **What to do next:**
   - **If something fails:**
     1. Send it to Photos:

        ```bash
        PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py remove 3-2 7-1
        ```

     2. In Photos, open "Remove from demo", select all and delete, empty Recently Deleted, and delete the album.
     3. Run `photosearch index` with `PHOTOSEARCH_DATA=data-demo` again.
     4. Go back to step 1 for a fresh take, because the take still shows the deleted photos.
   - **Once the rest of the sheets pass:**

     ```bash
     PHOTOSEARCH_DATA=data-demo uv run python tools/launch/check_take.py ok
     ```

   Repeat until `check_take.py` says every photo has been checked. Rediscover changes after each deletion, so a few new photos turn up each round.
7. **Cut it** (about a minute):

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run python tools/launch/edit.py
   ```

   This writes `launch.mp4` (16:9), `launch-vertical.mp4` (9:16) and `gifs/` into `data-demo/launch/`.
8. **Watch all of it before sharing.** Read Claude's answer too: it describes the photos it chose and left out.

## When the app changes

- **A view's buttons or names changed:** edit `tools/director/storyboard.py`. Each beat is a name, some JavaScript run in the page through `__demo` (cursor, typing, captions; see `overlay.js`), and seconds to hold. `WARM` lists views to load before recording, so map tiles and data are ready when they're shown.
- **Beats renamed or added:** `edit.py` cuts the web part at the `end` beat, and each GIF runs from one beat to another (`GIFS` at the top). Update those to match.
- **A different prompt or album:** change `PROMPT` and `ALBUM` in `common.py`. If Claude needs longer than about 4½ minutes, raise `--wait`. A fixed wait is used instead of waiting for text, because VHS throws the whole recording away when a wait times out.
