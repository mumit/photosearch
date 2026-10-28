# Recording the photosearch launch video

The launch video, recorded with [reshoot](https://github.com/mumit/reshoot): the web app acting out a storyboard,
Claude Code making an album, and a few seconds of the Photos window showing that album. Read `BRIEF.md` for the
scope. Run everything from this folder; it uses the photosearch checkout above it.

These run on a **separate demo Photos library**, never your own. Every photo a take can show is checked by eye before
anything is shared, and nothing is shared until a person has watched the result.

| File | What it is |
|---|---|
| `storyboard.toml` | The web take: search, ? Why, look-alikes, Galaxy, Photo Math, the map, Then and Now, with a result check per beat |
| `claude.tape` | The Claude take (VHS): Claude Code makes "Best hikes" from the demo library |
| `reset.py` | Before each run: demo library open in Photos, old album gone, Claude's MCP config written |
| `common.py` | What `reset.py` and `finish.sh` share: the album's name, AppleScript, the demo-library check |
| `edit.py` | Cuts web, Claude (8x while working) and the album in Photos into the videos and GIFs |
| `finish.sh` | After a run: records only the Photos window showing the album, then cuts and checks the final |
| `reshoot.toml` | The versioned project: app, takes, edit and check |

## Once

1. **Tools:** reshoot 0.3.13 or later, VHS, ffmpeg and Google Chrome (`brew install vhs ffmpeg`).
2. **A demo library.** In Photos, hold **Option** while opening it, choose **Create New…**, name it Photosearch Demo,
   and import only photos you're happy for anyone to see. Trips, landscapes, animals and food work well. **Leave
   out** people, screenshots, anything from near home, and anything with names, plates, house numbers or documents.
   Then index it into its own data folder, from the photosearch folder:

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run photosearch index
   ```

   The index remembers which library it came from, and adding to albums is refused unless that library is open.
3. **Claude's own config folder,** so the take shows a clean Claude Code with nothing from your usual setup. Log in
   once with whichever account you want on screen: `CLAUDE_CONFIG_DIR=~/.claude-demo claude`. In
   `~/.claude-demo/settings.json`, set `"promptSuggestionEnabled": false`, so no suggested prompt shows at the end.
4. **Screen Recording permission** for your terminal (System Settings → Privacy & Security), for the Photos window.

## Each time

1. Open the demo library in Photos: hold Option while opening Photos and pick Photosearch Demo, or, with Photos
   closed, `open -a Photos ~/Pictures/"Photosearch Demo.photoslibrary"`. Port 18766 must be free. The album shot
   takes the Mac's appearance, so switch to Dark for a dark one.
2. Check that the demo gives nothing of yours away (names, places near home, photo ids, locations, and faces or
   people found by macOS Vision), from the photosearch folder. Fix whatever it reports first.

   ```bash
   PHOTOSEARCH_DATA=data-demo uv run photosearch demo-check data
   ```

3. Check and try it at a lower resolution (about 10 minutes; Claude really makes the album):

   ```bash
   reshoot doctor --config reshoot.toml
   reshoot preview reshoot.toml
   ```

4. Record the final run (about 35 minutes, most of it the scan), then finish it with the Photos window. Leave Photos
   alone while these run: two scripts driving Photos at once can stall it.

   ```bash
   reshoot run reshoot.toml          # prints the run id
   sh finish.sh RUN_ID               # writes takes/final/RUN_ID-TIME/
   reshoot review takes/runs/RUN_ID
   ```

   The run's own `photosearch.mp4` has Claude's answer without the Photos window (versioned runs record browser
   and VHS takes only). The finished files are in `takes/final/RUN_ID-TIME/`:
   - `photosearch.mp4`, the whole video, and `photosearch.srt`, its captions;
   - `photosearch-new.mp4`, a short cut of what's new since the first launch video;
   - `photosearch-readme.gif` for the README, and `gifs/`, one per section for posts;
   - `review/`, the check sheets.
5. Watch all of it, read Claude's answer in full (it describes the photos it chose and left out), and look through
   the check sheets at full size. **What fails a photo:**
   - anyone at all, including heads at the frame's edge, tiny distant figures, reflections in aquarium glass, and
     people on boats or behind windows;
   - anything that identifies a person or place: names, plates, house numbers, documents, screens.

   When in doubt, it fails. Past misses were a straw hat at the edge of a frame, a silhouette in a lookout's mesh
   railing, and a blurred head under a hippo. Delete a photo that fails from the demo library in Photos (and from
   Recently Deleted), run `index` with `PHOTOSEARCH_DATA=data-demo` again, and record a new run, because the takes
   still show it. Otherwise record your verdicts: `reshoot accept RUN_ID` for the run, and
   `reshoot check --review takes/final/.../review --ok` for the final.

Keep earlier runs until a new one is accepted. Nothing here publishes anything.

## When the app changes

- A control moved or was renamed: fix its target in `storyboard.toml`; the beat's check says which one broke.
- Beats renamed: `edit.py` cuts the web part at `end`; the GIFs and the short cut name their beats at its top.
- A new cut or GIF only: `reshoot edit edit.py takes/runs/RUN_ID/takes/web.mp4 takes/runs/RUN_ID/takes/claude.mp4
  takes/final/.../photos-album.mov takes/final/...` makes them again from the recorded takes, without recording.
- Claude needs longer than about 4½ minutes: raise the final `Sleep` in `claude.tape`.
