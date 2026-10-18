# Roadmap

What to build next, in order. Move an item to **Done** when it ships, with its commit. New ideas go under **Later**.

## Next

## Later

**Experiments with the model** (measure each with `photosearch eval`):
- **Shorter or compressed vectors:** check whether the vectors can be cut to 256 numbers, or stored as int8 or 1-bit, and what that costs.
- **Other languages:** EmbeddingGemma is multilingual; test searches in other languages.
- **"Why did this match?":** cover parts of a photo one at a time, re-score it, and show a heat map.
- **Learn from ✕ and ☆:** train a small adjustment applied to every search from smart-album feedback.
- **Judge eval sheets in the web page or through MCP,** not only with `photosearch eval score`.
- **Quick first index:** 70 tokens first, so search works in about 30 minutes, then upgrade to 280.

**Fun:**
- **Recreate this:** an old photo of someone in a pose, to shoot again today and show side by side.
- **Family picks:** over LAN sharing, everyone stars favourites; the photo frame shows what the family liked.
- **Photo book:** a story exported as a print-ready PDF.
- **"Use as portrait"** on people pages.

**For people who find the repo:**
- CI on GitHub Actions (the tests already use a fake model).
- A one-command install.
- `serve` indexes new photos while it runs, instead of a nightly job (no background services).

## Done

- Then and Now: Play → Then and Now shows two photos from the same spot, years apart (`thennow.py`). Both need GPS (within 150 m), so only photos from 2016 on take part: matching old scans by look alone found different places that look alike. Often it's a younger sibling in the same spot years later. Not built: pairs with an old scan (they'd need a place), and pairs of the same person.
- Date detective: Play → Date Detective and `photosearch dates` date the photos with a placeholder date, a group at a time, from album names, album series, people and look-alikes. 851 of 1,042 are dated (the rest are small loose groups). Look-alikes turned out a weak clue (25 of 105 years right when the whole event is hidden). Not built: Apple's labels as a month clue.
- Real video search: `photosearch videos` embeds each video's sound (10 s pieces) and a frame every 3 s, and a search ranks a video by its best moment ("🔊 heard at 0:10"). Hovering flips through the frames. Sound matches were judged by ear to set `SOUND_AT`: Happy Birthday, laughing, clapping and music come up by sound; "a dog barking" finds kids shouting.
- Clutter and sensitive-photo sweep: Albums → Tidy up → Clutter and private photos lists IDs and cards, screenshots, receipts and papers, and accidental shots, and sends a kind to its own album in Photos. Accidental shots turned out hard: blur and darkness also find dim family photos, so only the clearest (floors, black frames) count. Sending isn't tried on my library yet (bd7a318).
- `photosearch eval`: compares two variants of the index (vision tokens, shorter or compressed vectors, another index), with blind sheets to judge. It reproduced the vision-token numbers (de6e9da).
- Vision tokens judged by eye: 70 is 4.7× faster and only slightly worse (552f91d).
- Writing to the main library tested: `album` from the terminal, `make_album` through Claude, Copy to Photos and Send the extras.
