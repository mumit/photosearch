# photosearch

Search your Apple Photos library by describing what's in a picture ("kids on a red slide at sunset"),
or find photos that look like one you pick. Everything runs on your Mac using Google's open
[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) model. No photos leave the machine.

It works with iCloud Photos and **"Optimize Mac Storage"**: it uses the preview images Photos already keeps
on disk, so nothing is downloaded from iCloud.

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

```bash
uv run python ps.py serve
```

Open **http://localhost:8765**. It works while `index` is still running, and picks up new photos as they're added.

| Tab | What it does |
|---|---|
| **Search** | Describe a photo. Filter by person (names you've tagged in Photos), date range, or photo/video. |
| **Galaxy** | Your whole library on one zoomable map, with similar photos next to each other and colored by year. Scroll to zoom, drag to pan, hover to peek. Type in *Light up…* to see where, say, "beach" lives. The first visit takes a minute to lay out the map. |
| **Time Machine** | Pick something that happens every year ("birthday cake", "christmas tree") and flip through the best match from each year. |
| **Play** | *Guess the Year* and *Guess the Place*, 10 rounds each. Works on a phone, for passing around. |
| **Photo Math** | Start from a photo or words, then add and take away ideas: *this photo + snow − summer*. |

Clicking any photo opens it large, with **More like this**, **Use in Photo Math** and **Open in Photos**
(the first time, macOS asks whether your terminal may control Photos; click OK). ← → browse.

*Guess the Place* loads its map from OpenStreetMap, so it needs internet; only map tiles are fetched, never your photos.

Stop the server with Ctrl-C.

### Search from the command line

```bash
uv run python ps.py search "dog on a beach at sunset"
```
```bash
uv run python ps.py search "birthday cake" --person Sam --after 2022-01-01 --before 2023-01-01 -k 50
```
```bash
uv run python ps.py similar <uuid>
```

Each result line shows score, date, photo/video, the photo's ID (uuid), place and people.

### Save results as a Photos album

```bash
uv run python ps.py album "Sunsets" "sunset over water" -k 60
```

This creates (or adds to) an album called "Sunsets" in Photos with the top 60 matches. **It's the only command
that changes your library.** It never deletes anything.

---

## 4. Files and cleanup

| Path | Contents |
|---|---|
| `ps.py` | All the code: indexing, search, album export, web server |
| `ui.html` | The web page served by `serve` |
| `data/index.sqlite` | One row per photo: date, place, GPS, people, albums, Apple's labels, and its 768-number vector |
| `data/thumbs/` | Small JPEG previews for the web page |
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

**Status:** full-library index in progress (M3 Pro: ~2 photos/s, ~2.5 h for 17k). Every web tab checked in headless
Chrome on a partial index. `album` has not been run yet.

**Ideas next:** an MCP server so Claude can search (and look at) your photos; smart albums you teach with a few
examples; duplicate cleanup; a year in review; index the audio track of videos.
