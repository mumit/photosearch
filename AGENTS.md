# Notes for coding agents

Read this before working on photosearch. [README.md](README.md) covers what the app does and how to use it. This file covers how I'd like you to work on it.

## Rules

- **Never write to my real Photos library** unless I ask for that specific change. Anything that adds to an album, imports or deletes goes to a demo library, or waits for me.
- **Never capture the whole screen.** A full-screen capture once showed my mail and calendar. Record one window (`screencapture -v -l<window id>`) or a headless browser page.
- **Nothing goes public without my yes.** This includes pushing, posting, publishing and sharing. I post on social media myself.
- **Keep secrets out of output and git.** My TypeSafe Jev key is `TYPESAFE_API_KEY`, in the environment or a git-ignored `.env`. Don't print it.
- **Photos shown in public come from the demo library only,** and every one is checked by eye at full size first. See [tools/launch/README.md](tools/launch/README.md).
- **No login items or background services** (launchd) unless I ask.
- Commit only when I ask, in conventional-commit style (`feat(galaxy): …`, `fix(mcp): …`).

## Layout

| Path | What it is |
|---|---|
| `src/photosearch/` | The package. `cli.py` has the commands, `server.py` the web app, `mcp_server.py` the tools Claude uses, `embed.py` the model. |
| `src/photosearch/evals.py` | `photosearch eval`: measures a change to the index (vision tokens, shorter or compressed vectors), judged blind. Use it for any experiment with the model. |
| `src/photosearch/web/` | The page: `index.html`, `app.css`, `js/*.js`. Re-read on every request, so no build step. |
| `tests/` | pytest, on a made-up library with a fake model. |
| `tools/director/` | Records the web app in headless Chrome from a storyboard. |
| `tools/launch/` | Reshoots the launch video. Its README is the step-by-step guide. |
| `data/` | My index, thumbnails and logs. Git-ignored and personal. |
| `data-demo/` | The demo library's index and launch takes. Git-ignored. |

`PHOTOSEARCH_DATA` points the app at another data folder, such as `data-demo`.

## Commands

```bash
uv run pytest                 # fast tests (about 190)
uv run pytest -m browser      # headless-Chrome tours of the page (slow)
uv run photosearch serve      # the web app on localhost:8765
PHOTOSEARCH_DATA=data-demo uv run photosearch serve --demo --port 8766   # presenter mode on the demo index
```

## Pitfalls

- **Photos and AppleScript hang when called from a worker thread** (the MCP server, the web server). Run them in a subprocess: `make_album` calls `photosearch add-to-album`, and full-size fetches call `photosearch fetch`. A regression once made `make_album` hang for 120 s.
- **Tests must not start Photos-touching subprocesses.** The subprocess escapes the tests' fakes and reaches the real library.
- **Two scripts driving Photos at once can stall it** until it's force-quit.
- **Torch on MPS crashes the process if two threads encode at once.** `embed_query` holds a lock.
- **My dates for undated photos live in the `redated` table.** `photosearch index` rewrites `photos.date` from Photos, then `dates.apply` puts mine back. Anything else that rewrites dates must do the same.
- **`index` also reads new videos on the Mac** (videos.py), which loads the model's audio encoder. `--no-videos` skips that; `--limit` trials skip it too.
- **PhotoKit crashes (SIGSEGV, in pyobjc) exporting an edited video.** `videos --icloud` downloads originals, in a `photosearch download-videos` process, so a crash costs one video, not the run.
- **PhotoKit downloads stay in the Photos library.** `fetch` and `videos --icloud` leave each original on disk in Photos until it frees space, so a big run uses many GB.
- **Vectors from different settings don't mix.** The index records its model and vision tokens and refuses others.
- **Headless Chrome won't go below a 500 px window.** For phone layouts, use `Emulation.setDeviceMetricsOverride` and check that `innerWidth` equals the target width.
- **VHS throws away the whole recording when a `Wait` times out,** so the Claude take uses a fixed `Sleep`.
- **The Jev model's yes/no answers need cut-offs of 0.7 to 0.85, not 0.5.** Measure on labelled examples before relying on a new question.

## Direction

I want it fun first: for me now, maybe for my family later. Keep the page usable on phones. LAN sharing (`serve --lan`) is opt-in and stays off by default. For yes/no or pick-one decisions, I prefer cheap decision models (Jev) to a generative LLM, measured first.

What to build next is in [ROADMAP.md](ROADMAP.md). Keep it current: move items to Done when they ship.

## Open work

Update this section when something finishes or starts.

- **Launch posts:** Highlight important changes so I can post those to X/LinkedIn.
- **Demo leftovers:** the demo Photos library, its import folder, `data-demo/` and a separate Claude config folder for the demo takes are still on disk. I haven't decided whether to keep them. Before the demo library is deleted, Photos must be switched back to my library (hold Option while opening Photos).
- **Date detective:** done. 851 of 1,042 undated photos are dated; the rest are small loose groups.
- **Then and now:** done (Play → Then and Now, `thennow.py`): same spot and same person.
- **Recreate this:** built (Play → Recreate This, `recreate.py`, ROADMAP item 1). Waiting on me to take one again, so the match cut-off can be checked.
- **Video search:** done. All 752 videos are read; `index` reads new local ones, and `videos --icloud` the rest. `SOUND_AT` was set from my marks by ear (`data/sound-marks.json`, README → Videos).
- **Clutter sweep:** built (Albums → Tidy up → Clutter and private photos). Sending a kind to Photos isn't tried on my library yet, and `photosearch index` needs one run to read Photos' screenshot marks.
- **Why did this match:** done (? Why in the big photo view, `photosearch why`, `why.py`). A post is drafted.
- **Vision tokens:** done. 70 tokens is 4.7× faster, changes the first result in more than half of searches, but is only slightly worse when judged by eye (see the README's Measurements). 280 stays the default.
