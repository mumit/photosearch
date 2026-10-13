# photosearch

Semantic search over your Apple Photos library with Google's EmbeddingGemma 2, fully on-device.

```bash
uv run python ps.py index            # incremental; re-run any time to pick up new photos
uv run python ps.py serve            # web UI at http://localhost:8765
uv run python ps.py search "dog on a beach at sunset" --after 2022-01-01 --person Sam
uv run python ps.py similar <uuid>
uv run python ps.py album "Sunsets" "sunset over water" -k 60   # writes an album into Photos
```

- Reads the library with [osxphotos](https://github.com/RhetTbull/osxphotos) (read-only, except `album`).
- Embeds the local preview Photos keeps for every item, so nothing is downloaded from iCloud.
  Videos are indexed by their poster frame only.
- Everything lives in `data/`: `index.sqlite` (metadata + 768-d float32 vectors, ~3 KB/photo)
  and `thumbs/` (360 px JPEGs for the UI).
- Search is brute-force cosine in NumPy; at ~17k items that's a few ms, so no vector DB is needed.

## Status / findings (first Mac: M3, 16 GB)

- Library: ~17k items (16.2k photos, 750 videos); 13.3k originals are iCloud-only, but **every item
  has a local preview**, so indexing needs no downloads.
- 300-photo trial indexed and stored fine (~3 KB vector + ~25 KB thumbnail per photo).
- **Speed is the bottleneck.** Measured image embedding on the M3 GPU:

  | setup | photos/s | 17k library |
  |---|---|---|
  | PyTorch MPS bf16, 280 vision tokens (default) | ~1.2 | ~4 h |
  | PyTorch MPS bf16, **70 vision tokens** | ~4.6 | ~1 h |
  | MLX `mlx-community/embeddinggemma-2-bf16` (mlx-vlm) | ~1.3 | ~4 h — no gain, dropped |
  | CPU fp32 | ~0.3 | — |

  70-token vectors have mean cosine 0.95 to the 280-token ones; whether that hurts *ranking* on your
  photos is untested. Google's 27 img/s is quoted for an M5 Pro, at 70 tokens.
- Don't use float16 (model card: NaNs / silent degradation). bf16 on MPS is fine.
- The "photo anchor" (pastel-labs on Hugging Face) is only useful for 1-/4-bit compressed vectors.
  At this library size full float32 vectors are ~50 MB, so it isn't needed.

## Next steps (on the M4)

1. `uv sync`, then `uv run python ps.py index --limit 500` and compare speed at `--vision-tokens 280` vs `70`.
   The index must use one budget throughout: delete `data/` before switching.
2. Index everything, run `serve`, and compare 20–30 real queries against Photos' own search.
3. Not yet exercised: `serve` (web UI), `search`/`similar` on real photos, `album`. Test these first.
4. Then: video audio track, captions with a small VLM for hybrid search, MCP server.

Needs Full Disk Access for your terminal app if osxphotos can't open the library.
