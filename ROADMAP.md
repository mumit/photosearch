# Roadmap

What to build next, in order. Move an item to **Done** when it ships, with its commit. New ideas go under **Later**.

## Next

### 1. Evaluation harness: `photosearch eval`

Turn the vision-token test into a command:
- a fixed set of searches;
- blind side-by-side sheets of two settings' top results, in random order;
- a judge: me, or Claude through MCP;
- a score written to the README's Measurements.

Every later experiment then gets a number. `tools/rank_test.py` is the starting point.

**Done when:** `photosearch eval A B` compares two indexes or settings, and the vision-token numbers can be reproduced with it.

### 2. Date detective

1,042 photos carry a placeholder date (2002-01-01). They're missing from On this day, Time Machine, stories, Guess the Year and the galaxy's years.

Estimate each one's date from:
- its dated look-alikes;
- who's in it, since children change a lot from year to year;
- Apple's labels (snow, Christmas tree).

Then play the best guesses as Guess the Year with real stakes: my answer becomes the date. Keep the dates in photosearch's index, never write them to Photos.

**Done when:** most undated photos have a confirmed or confident date, and the features above include them.

### 3. Clutter and sensitive-photo sweep

Find screenshots, receipts, accidental pocket shots, ID cards and other documents. Put them in a review album in Photos, as Tidy up does. Nothing is deleted.

**Done when:** a Tidy up section lists them by kind, and sends a chosen kind to an album.

### 4. Real video search

- Embed each video's audio with the model's audio encoder (skipped today), so "laughing", "Happy Birthday being sung" or "waves" find videos. Check first that audio vectors land in the same space as text and images.
- Embed several frames per video, so a search can open a long clip at the right moment.
- Show a preview when hovering over a video.

**Done when:** a sound search finds videos that the frames alone don't.

## Later

**Experiments with the model** (measure each with the harness):
- **Shorter or compressed vectors:** check whether the vectors can be cut to 256 numbers, or stored as int8 or 1-bit, and what that costs.
- **Other languages:** EmbeddingGemma is multilingual; test searches in other languages.
- **"Why did this match?":** cover parts of a photo one at a time, re-score it, and show a heat map.
- **Learn from ✕ and ☆:** train a small adjustment applied to every search from smart-album feedback.
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

- Vision tokens judged by eye: 70 is 4.7× faster and only slightly worse (552f91d).
- Writing to the main library tested: `album` from the terminal, `make_album` through Claude, Copy to Photos and Send the extras.
