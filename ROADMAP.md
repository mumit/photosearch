# Roadmap

What to build next, in order. Move an item to **Done** when it ships, with its commit. New ideas go under **Later**.

## Next

### 1. Date detective

**Built, waiting on my answers:** Play → Date Detective, and `photosearch dates`. It uses album names, album series,
people and look-alikes. Look-alikes turned out weak (25 of 105 years right when the whole event is hidden), so I
confirm every group. Not built: Apple's labels as a month clue.

1,042 photos carry a placeholder date (2002-01-01). They're missing from On this day, Time Machine, stories, Guess the Year and the galaxy's years.

Estimate each one's date from:
- its dated look-alikes;
- who's in it, since children change a lot from year to year;
- Apple's labels (snow, Christmas tree).

Then play the best guesses as Guess the Year with real stakes: my answer becomes the date. Keep the dates in photosearch's index, never write them to Photos.

**Done when:** most undated photos have a confirmed or confident date, and the features above include them.

### 2. Real video search

**Built, waiting on two things:** `photosearch videos` embeds each video's sound (10 s pieces) and a frame every 3 s.
Search ranks a video by its best moment and shows it ("🔊 heard at 0:10"). Hovering flips through the frames, and
the big view has a strip of them. `index` also reads new videos already on the Mac.
- Run `photosearch videos --icloud` for the other 702. About 75 minutes, and Photos keeps the downloaded originals (38 GB).
- Judge the top sound matches by ear, and set `SOUND_AT` (where a sound ranks among photos) from that.

- Embed each video's audio with the model's audio encoder (skipped today), so "laughing", "Happy Birthday being sung" or "waves" find videos. Check first that audio vectors land in the same space as text and images.
- Embed several frames per video, so a search can open a long clip at the right moment.
- Show a preview when hovering over a video.

**Done when:** a sound search finds videos that the frames alone don't.

## Later

**Experiments with the model** (measure each with `photosearch eval`):
- **Shorter or compressed vectors:** check whether the vectors can be cut to 256 numbers, or stored as int8 or 1-bit, and what that costs.
- **Other languages:** EmbeddingGemma is multilingual; test searches in other languages.
- **"Why did this match?":** cover parts of a photo one at a time, re-score it, and show a heat map.
- **Learn from ✕ and ☆:** train a small adjustment applied to every search from smart-album feedback.
- **Judge eval sheets in the web page or through MCP,** not only with `photosearch eval score`.
- **Quick first index:** 70 tokens first, so search works in about 30 minutes, then upgrade to 280.

**Fun:**
- **Then and now:** photos from the same spot years apart, matched by GPS and by look.
- **Recreate this:** an old photo of someone in a pose, to shoot again today and show side by side.
- **Family picks:** over LAN sharing, everyone stars favourites; the photo frame shows what the family liked.
- **Photo book:** a story exported as a print-ready PDF.
- **"Use as portrait"** on people pages.

**For people who find the repo:**
- CI on GitHub Actions (the tests already use a fake model).
- A one-command install.
- `serve` indexes new photos while it runs, instead of a nightly job (no background services).

## Done

- Clutter and sensitive-photo sweep: Albums → Tidy up → Clutter and private photos lists IDs and cards, screenshots, receipts and papers, and accidental shots, and sends a kind to its own album in Photos. Accidental shots turned out hard: blur and darkness also find dim family photos, so only the clearest (floors, black frames) count. Sending isn't tried on my library yet (bd7a318).
- `photosearch eval`: compares two variants of the index (vision tokens, shorter or compressed vectors, another index), with blind sheets to judge. It reproduced the vision-token numbers (de6e9da).
- Vision tokens judged by eye: 70 is 4.7× faster and only slightly worse (552f91d).
- Writing to the main library tested: `album` from the terminal, `make_album` through Claude, Copy to Photos and Send the extras.
