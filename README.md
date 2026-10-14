# photosearch

Search your Apple Photos library by describing what's in a picture ("kids on a red slide at sunset"),
or find photos that look like one you pick. Everything runs on your Mac using Google's open
[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) model. No photos leave the machine.

It works with iCloud Photos and **"Optimize Mac Storage"**: indexing and search use the preview images Photos
already keeps on disk, so nothing is downloaded from iCloud for them. Those previews can be tiny (256 px for photos
kept only in iCloud), so when a photo is shown big (opened full size, or in a story) Photos is asked for its
full-size version, which is kept in `data/large/`. See [Photo quality](#photo-quality).

---

## 1. Requirements

| | |
|---|---|
| **Mac** | Apple Silicon (M1 or later). Intel Macs work but are much slower (CPU only). |
| **macOS** | A recent version with the Photos app and a Photos library (iCloud or local). |
| **Memory** | 16 GB recommended; 8 GB works for small batches. |
| **Disk** | About **3 GB** for software + model, plus about **30 KB per photo** for the index (about 500 MB for 17,000 photos). |
| **Network** | Needed once, to download Python packages (about 1 GB) and the model (about 1.5 GB). Not needed after that. |

### What gets installed

| Component | What it is | Size | Where it goes |
|---|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python package/environment manager | ~40 MB | `~/.local/bin/uv` |
| Python 3.12 | Installed automatically by uv if missing | ~60 MB | uv's own folder |
| Python packages | PyTorch, sentence-transformers, transformers, osxphotos, Pillow, pillow-heif, NumPy | ~1 GB | `.venv/` in this repo (backed by `~/.cache/uv`) |
| **Model: `google/embeddinggemma-2`** | Multimodal embedding model (text + images in one vector space). Apache 2.0, not gated, no account or token needed. Only the text and vision parts are loaded (440M of 740M parameters); the audio encoder is skipped. | ~1.5 GB | `~/.cache/huggingface/hub/` |

No other models are needed. The repo doesn't use any API keys or cloud services.

---

## 2. Install

### Step 1: Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

(or, with Homebrew: `brew install uv`). Open a new Terminal window afterwards so `uv` is on your PATH, and check:

```bash
uv --version
```

### Step 2: Clone the repo

```bash
git clone https://github.com/mumit/photosearch.git
```
```bash
cd photosearch
```

### Step 3: Install Python and the packages

```bash
uv sync
```

This creates `.venv/` with the exact versions pinned in `uv.lock`, and installs Python 3.12 first if you don't have it.

### Step 4: Download the model (optional; otherwise it downloads on first run)

```bash
uv run hf download google/embeddinggemma-2
```

You may see a warning about "unauthenticated requests". That's harmless: the model is public.

### Step 5: Let your terminal read the Photos library

macOS protects the Photos library. If the next step fails with **"Operation not permitted"**, give your terminal
app Full Disk Access:

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Turn on the app you run commands from (Terminal, iTerm, VS Code, …). Use **+** to add it if it isn't listed.
3. Quit and reopen that app.

Check that it works. This prints your library path and how many items it has:

```bash
uv run python -c "import osxphotos; d = osxphotos.PhotosDB(); print(d.library_path, len(d.photos()))"
```

If you have more than one library, this shows the one Photos currently uses as the **System Photo Library**.
To index a different one, pass `--library "/path/to/Other Library.photoslibrary"` to `index`.

---

## 3. Run

### Build the index

Start with a small trial to check speed on your Mac:

```bash
uv run python ps.py index --limit 500
```

It prints progress, photos per second and an estimated time remaining. Then index everything:

```bash
uv run python ps.py index
```

- Indexing is **incremental**: you can stop it (Ctrl-C) and re-run it later, and it continues where it left off.
  Run it again any time to add new photos.
- Newest photos are indexed first.
- Expect the Mac to run warm while it works; it's using the GPU.

**Speed vs. quality:** each image is given to the model as a number of "vision tokens" (default 280).
`--vision-tokens 70` is about 4× faster at some cost in search quality:

```bash
uv run python ps.py index --vision-tokens 70
```

Use one setting for the whole index (it's recorded, and `index` refuses to mix). To switch, delete the `data/` folder and re-index.
Each run also refreshes people, albums and places for photos already indexed, and drops photos you've deleted.

### Search and play in the browser

This doesn't need Claude. From the `photosearch` folder, in any terminal:

```bash
uv run python ps.py serve
```

Open **http://localhost:8765**. It works while `index` is still running, and picks up new photos as they're added.

One search box at the top works everywhere (press **/** or **⌘K** to jump to it). As you type, it suggests the
people, places, trips and years that match, and offers the same words in the other modes ("through the years",
"light up in the galaxy"). Filters (who, where, when, season, photos or videos, *without…*) sit behind the ☰ button
and show as chips you can remove. On a phone, the modes move to a dock at the bottom.

| Mode | What it does |
|---|---|
| **Home** | Opens on **On this day**: a slow slideshow of today's date in earlier years, most striking first, which trip you were on (with a link to its story), and ‹ › to step through other days (`ps.py today` does the same in the terminal). Below it are shelves: *Rediscover* (random photos worth another look, ↻ to shuffle), the people you've tagged, your trips, ideas to search for, the other modes, *Day by day* (a calendar of the year, each day coloured by how many photos it has; hover for its best photo, click for the day) and your years. Photos that look like documents, screenshots or ID cards are left out. |
| **Search** | Describe a photo. Results keep their shape, in rows like a photo book, sorted by best match or by date. Picking a person or place from the suggestions shows their most interesting photos. Put what you *don't* want in **without…** (e.g. "selfies"): the model is weak at "no …" inside the description. Every search has its own address, so back and forward work. |
| **People** | A page per person tagged in Photos: their best photo from every year (**▶ through the years** plays them in turn), who they're most often photographed with, their places and favourite photos. Portraits are picked by the search model as the closest thing to a close-up of a face. Names anywhere (suggestions, the big photo view) lead here. |
| **Map** | Everywhere you've been, each place as a pin showing its best photo and how many were taken there. It opens on home; chips along the bottom fly to the other regions (named like trips: "Lisbon", "Sintra & Cascais") or show everywhere. Nearby places merge until you zoom in. Tap a pin for that place's best photos, or **▶ Slideshow** them. Map tiles come from OpenStreetMap (so it needs internet); your photos never leave the Mac. |
| **Galaxy** | Your whole library on one zoomable map, with similar photos next to each other and colored by year. Scroll to zoom, drag to pan, hover to peek. Type in the search box to see where, say, "beach" lives. The first visit takes a minute to lay out the map. |
| **Time Machine** | Pick something that happens every year ("birthday cake", "christmas tree") and flip through the best match from each year. ▶ or space plays them in turn. |
| **Play** | *Guess the Year*, *Guess the Place* and *Which Came First?* (two photos: tap the older one). Play alone (10 rounds, best scores kept) or add players to pass the phone around: everyone gets 5 turns and the end shows who won. **Photo Math** lives here too: start from a photo or words, then add and take away ideas, *this photo + snow − summer*. |
| **Photo frame** | `#frame`, or from Home: a slow, endless full-screen slideshow of your best photos with the time and date, for a spare iPad or TV. It keeps the screen awake. **⚙ What to show** picks everything, on this day, one person, or any search (`#frame/?person=…`, `#frame/?q=…`). **▶ Slideshow** on any search, place or open photo plays just those. |
| **Stories** | Every trip (found automatically from where photos were taken) and every year as a slideshow of its best, most varied moments, with chapters and captions. **⤓** saves one as a single HTML file (photos included) you can send to family; **✎** edits it. |

**✨ Smart search (optional).** With a [TypeSafe](https://typesafe.ai) API key, the search box fills in the
filters from your description: *"Sam at the beach last summer, no selfies"* becomes person Sam, summer 2025,
without selfies. The chips it adds are amber, so you can see and remove what it understood; untick ✨ in the filters
to turn it off. Put the key in a `.env` file next to `ps.py` (it's git-ignored):

```
TYPESAFE_API_KEY=...
```

Names and years are matched on your Mac. Only the description goes to TypeSafe's Jev model, with tagged names
replaced by "someone"; no photos or library data are sent. Without a key, search works as before.

Clicking any photo opens it large, on a blur of its own colours. Along the bottom is a row of look-alikes (or, with
**📅 Same day**, the other photos from that day): tap one to wander, with a trail of dots to go back. Names and the place are links to more
of them; **📅 This day** shows the same date in other years; **∑ Math** starts Photo Math from it; **Open in Photos**
shows it in the Photos app (the first time, macOS asks whether your terminal may control Photos; click OK).
← → or a swipe browse; Esc or a swipe down closes. Press **?** anywhere for all the shortcuts.

Search results come 48 at a time; **Show more** at the bottom fetches the next batch.

*Guess the Place* loads its map from OpenStreetMap, so it needs internet; only map tiles are fetched, never your photos.

Stop the server with Ctrl-C. It only runs while that terminal window is open. Claude is only needed for the
MCP features (asking about photos in chat, curated stories); everything in the web page works without it.

### Search from the command line

```bash
uv run python ps.py search "dog on a beach at sunset"
```
```bash
uv run python ps.py search "birthday cake" --person Sam --after 2022-01-01 --before 2023-01-01 -k 50
```
```bash
uv run python ps.py search "group photos at a party" --exclude "a selfie" --place Portland
```
```bash
uv run python ps.py similar <uuid>
```

Each result line shows score, date, photo/video, the photo's ID (uuid), place and people.

### Ask Claude about your photos (MCP)

`mcp_server.py` exposes the index to Claude Code (or any MCP client). Register it once:

```bash
claude mcp add --scope user photosearch -- uv run --directory "$PWD" python mcp_server.py
```

Then, in a new Claude Code session, ask things like *"find photos of Sam at the beach, no selfies, and make an
album"*. Claude searches, **looks at the results** on a numbered contact sheet, drops the wrong ones, and only then
answers or builds the album. Tools: `search_photos` (with `exclude`, people, place, date and kind filters),
`similar_photos`, `best_per_year`, `view_photos`, `library_overview`, `on_this_day`, `list_stories`, `story_highlights`, `save_story`,
`make_album` (adds only, never removes).

### Stories: trips and years

A **trip** is a run of days when most photos were taken 75+ km from home (home is worked out per year, from where
you take photos on the most days). Trips are named from Photos' place data (*Lisbon*, *Minneapolis & Saint Paul*) and
need 20+ photos. `uv run python ps.py trips` lists them.

Every trip and year gets an automatic story the first time you play it: highlights by day for a trip, by month for a
year, captioned with who's in them. For a nicer one, ask Claude (with the MCP server set up) *"make a story of our
Lisbon trip"* or *"make a year in review for 2025"*. It looks through the highlights and searches for anything
missing (food, streets), keeps the best ~24 (skipping repeats, blurry shots and too many selfies), and writes
chapters and captions. Captions stick to what's in the photo and the names tagged in Photos. Trip stories leave out
photos taken near home (the morning you left).

**✎** on a story's card opens the editor: drag photos to reorder them or move them between chapters (on a phone or
iPad, press and hold a photo first), ↻ swap one
for a look-alike from the same days, ✕ remove, **+ Add photos** (that story's highlights, or search within its days),
and edit the title, chapter titles and captions. Changes save as you go, with undo (⌘Z). The page's save endpoint is
the only one that writes, and it only accepts JSON from the page itself.

```bash
uv run python ps.py review trip-2024-05-02 --export lisbon.html   # or a year: review 2025
```

writes the slideshow as a single file you can AirDrop, email or put on a USB stick. It contains the photos, so share
it only with people who should see them.

Highlights are picked locally: the most interesting-looking photos (family photos count a little extra), with
near-duplicates removed and picks spread across events (runs of photos without a day-long gap).

### Save results as a Photos album

```bash
uv run python ps.py album "Sunsets" "sunset over water" -k 60
```

This creates (or adds to) an album called "Sunsets" in Photos with the top 60 matches. **It's the only command
that changes your library.** It never deletes anything.

---

### Photo quality

With *Optimize Mac Storage*, Photos keeps only a small preview of most photos on the Mac (here 60% are 256–511 px;
the rest about 2048 px). That's plenty for the model and for the grid, but blurry full screen. So:

- **Opening a photo** (search, Time Machine, the games) shows the preview at once, then asks Photos for the full-size
  version and swaps it in (about 1 s; longer if iCloud is slow).
- **Stories** fetch theirs when you play one, save one, or Claude saves one; **⬇ Download** and `review --export`
  wait for any still missing, so the file you send is sharp (1600 px, ~0.5 MB a photo).
- `uv run python ps.py fetch trip-2024-05-02` (or `2025`, or photo uuids) fetches ahead of time, e.g. before
  showing a story offline. `uv run python ps.py thumbs` rebuilds thumbnails after changing their size.

Fetching uses Photos' own API (PhotoKit), in a separate process, and doesn't change the library. The first time,
macOS may ask to let your terminal access Photos. To have everything sharp without fetching, turn on **Photos →
Settings → iCloud → Download Originals to this Mac** (this needs disk space for the whole library).

## 4. Files and cleanup

| Path | Contents |
|---|---|
| `ps.py` | All the code: indexing, search, album export, web server |
| `ui.html` | The web page served by `serve` |
| `mcp_server.py` | MCP server so Claude can search, view and make albums |
| `review.html` | The story slideshow player (also used for the one-file export) |
| `data/reviews/` | Saved story picks and captions, one JSON file per year (`2025.json`) or trip (`trip-2024-05-02.json`) |
| `.env` | Optional `TYPESAFE_API_KEY` for ✨ smart search (git-ignored) |
| `data/index.sqlite` | One row per photo: date, place, GPS, people, albums, Apple's labels, and its 768-number vector |
| `data/thumbs/` | Small JPEG previews for the web page (512 px) |
| `data/large/` | Full-size copies (up to 2560 px) of photos shown big whose local preview was small, fetched from iCloud. Safe to delete; they come back when needed |
| `data/galaxy.json` | The Galaxy map layout (rebuilt automatically when the index grows by 10%) |

`data/` holds previews of your photos, so treat it as private. It's in `.gitignore` and never committed.

To remove everything:

```bash
rm -rf data .venv
```
```bash
uv run hf cache rm model/google/embeddinggemma-2
```

(or delete `~/.cache/huggingface/hub/models--google--embeddinggemma-2`). `uv cache clean` frees the shared
package cache, but it affects all uv projects on the Mac.

---

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| `Operation not permitted` / can't open library | Full Disk Access for your terminal (Step 5), then restart the terminal. |
| `uv: command not found` | Open a new Terminal window after installing uv, or run `source ~/.zshrc`. |
| Very slow (under 1 photo/s) | Check the Mac is Apple Silicon. Try `--vision-tokens 70`, and close other heavy apps. |
| Out of memory | Lower the batch size: `index --batch 4`. |
| Some photos "skipped" | They have no local preview yet (e.g. just synced). Re-run `index` later. |
| Opened photos stay blurry | The full-size fetch failed: offline, iCloud slow, or Photos access not allowed for your terminal (**System Settings → Privacy & Security → Photos**). Try `ps.py fetch <uuid>` to see the error. |
| Clicking a photo doesn't open Photos | Allow it in **System Settings → Privacy & Security → Automation**. |
| `Could not get path to photo library database` | osxphotos couldn't work out the system library. It falls back to `~/Pictures/Photos Library.photoslibrary`; for another location pass `--library`. |
| `index was built with vision_tokens=…` | The index remembers its settings so vectors don't get mixed. Use the same `--vision-tokens`, or delete `data/` and re-index. |

Don't switch the model to float16: it produces broken vectors (NaNs). The code uses bfloat16 on the GPU, which is safe.

---

## 6. How it works

1. **osxphotos** reads the Photos database (dates, places, people, albums) and finds each item's largest
   on-disk preview. For videos, that's the poster frame.
2. **EmbeddingGemma 2** turns each preview into a 768-number vector, and turns your search text into a vector
   in the same space (with the prefix `task: search result | query:`).
3. Search ranks every photo by cosine similarity to the query vector. At this scale that's a few
   milliseconds in NumPy, so no vector database is needed.

---

## Development notes

Measured on an M3 MacBook (16 GB) with a 17k-item library (16.2k photos, 750 videos, 13.3k originals in iCloud only):

| Setup | Photos/s | Full library |
|---|---|---|
| PyTorch MPS bf16, 280 vision tokens (default) | ~1.2 | ~4 h |
| PyTorch MPS bf16, 70 vision tokens | ~4.6 | ~1 h |
| MLX (`mlx-community/embeddinggemma-2-bf16` via mlx-vlm) | ~1.3 | ~4 h (no gain, dropped) |
| CPU fp32 | ~0.3 | — |

- 70-token vectors have mean cosine 0.95 to the 280-token ones. The effect on ranking quality is untested.
- The "photo anchor" published by pastel-labs on Hugging Face only matters for 1- or 4-bit compressed vectors. It isn't needed at this size.

- Some photos (very dark, very plain) score fairly high for any query. A CSLS-style penalty using Apple's labels as a
  query bank was tried on ~5k photos and made results worse (it boosted documents and handwriting), so search uses
  plain cosine.
- Galaxy uses UMAP (`min_dist=0.6`, so near-duplicates spread out instead of piling up) and k-means regions named by
  the Apple labels that are most distinctive for each region.

- Negation: `exclude` subtracts 0.5× the excluded text's vector from the query (as Photo Math does). On
  "group photos at a party" minus "a selfie" it removed the selfies; for "no people" in landscapes the plain query
  already worked.
- Laya (open "System One" decision model) was trialled for parsing the search box on 20 labelled queries: 20/20 on
  "wants no people" / "no selfies", but 12/20 photo-vs-video, 14/20 time period, 17/20 season, ~430 ms per query on CPU
  and ~1.5 GB. Not adopted: keyword rules beat it on the choice questions, and the explicit **without…** field covers
  negation for free. Through MCP, Claude does the parsing anyway.
- Jev (TypeSafe's hosted System One model) on the same 20 queries: 19/20 photo-vs-video, 20/20 time period, 18/20
  season, ~115 ms. Its yes/no answers needed higher cut-offs than 0.5 (0.7 for "no people", 0.85 for "no selfies");
  on 20 fresh queries with those cut-offs it got 95/100. It powers the optional ✨ smart search. Choices under 60%
  confidence are ignored.

**Status:** full library indexed (16,975 items in 140 min on an M3 Pro; 42 skipped for lack of a local preview). Every web tab checked in headless
Chrome. `album` / `make_album` have not been run yet. 1,042 photos carry a placeholder date (2002-01-01 00:00); they are treated as undated.

**Ideas next:** smart albums you teach with a few examples; duplicate cleanup;
index the audio track of videos.
