# Roadmap

What to build next, in order. Move an item to **Done** when it ships, with its commit. New ideas go under **Later**.

## Next

### 1. Recreate this

**Built, waiting on a real recreation:** Play → Recreate This (`recreate.py`). Ideas are old posed photos of one or
two named people; picks go on a list in this index; a newer photo of the same person that looks alike (0.80) is
offered as the new shot to confirm. The 0.80 is a guess until a real recreation is matched.

**Done when:** a photo I took again is found and shown with the old one.

## Later

**Experiments with the model** (measure each with `photosearch eval`):
- **Learn from ✕ and ☆:** train a small adjustment applied to every search from smart-album feedback.

**Fun:**
- **Photo book:** a story exported as a print-ready PDF.

**For people who find the repo:**
- CI on GitHub Actions (the tests already use a fake model).
- A one-command install.
- `serve` indexes new photos while it runs, instead of a nightly job (no background services).

## Done

- Use as portrait: 👤 Portrait in the big photo view (on the Mac) makes a photo someone's portrait everywhere. Every portrait, picked or chosen, is now cropped around that person's face, from where Photos says it is (`index` reads it; `people.py`).
- Judge a test: Play → Judge a Test shows an experiment's blind sheets on any device, one search at a time, each judge under their own name, with the results once every search is judged and how often two judges agree. Claude judges through MCP (`eval_sheet`, `score_eval_sheet`). `photosearch eval` also compares rules for ranking over the whole library (`search`, `search=nohub`, `search=check`).
- ✨ smart search checks the first photos: Jev, given each of the first 40 photos described in words (labels, what the model sees, time, people count, brightness and colour; never the photo or a name), nudges their order. Judged blind, the first 10s of 16 weak searches held 136 fitting photos of 160, not 121; 8 of 20 everyday searches got better and 2 worse. About 0.35 s a search (`checks.py`, FINDINGS.md).
- Words in photos: `photosearch text` (and each `index` run) reads the words in every photo with Apple's Vision, in 14 minutes for 16,200 photos. Words in "quotes" in a search must be written in the photo. Measured first: the model already reads big, clear text, and a boost for read words made 34 word searches and 115 everyday ones worse, judged blind, but the model misses most small print (FINDINGS.md).
- Where search breaks down, measured: 65 searches in 10 groups judged by eye (84% fit). Searches for how a photo looks (close-up, black and white, dusk) and printed pages did worst, mostly from accidental shots and plain textures that match everything. Those now count for a little less in searches by words (`hub_penalty`), which judged blind made the first 10 better on 115 searches (FINDINGS.md).
- Family picks: ♡ Love in the big photo view, from the Mac or a phone with `serve --lan`, under the name each device gives. Home shows the family's picks, most loved first, and the photo frame plays everyone's or one person's, saying who loved each (`picks.py`). The frame's place and people line, hidden since a filter box took its id, shows again.
- Quick first index: `photosearch index --quick` indexes at 70 vision tokens (about 4× faster), and the next plain `index` redoes those photos at 280, newest first. Quick vectors are moved back along the words' direction so a half-redone index ranks fairly.
- Other languages, measured: searches in Spanish, French, Hindi, Chinese, Arabic and Bengali fit about as well as English, judged blind (88 to 104 of 120 photos, English 94). Nothing to build; the README says so.
- Shorter or compressed vectors, measured: int8 changes almost nothing, 256 numbers or 1 bit change a lot, and none is needed at 17,000 photos (52 MB, 0.6 ms a search).
- Why did this match: **? Why** on a photo from a search, and `photosearch why`, show how much each word counts, what the model sees (Photos' labels as words) and where in the photo it matched (`why.py`). The map comes from the model's own squares in one pass (0.5 s), not by covering parts one at a time (16 s), and passed the same cover test better. A match on the whole scene is said, not drawn. Small things in busy photos light up weakly.
- Then and Now: Play → Then and Now shows two photos years apart (`thennow.py`). *Same spot* needs GPS on both (within 150 m), so only photos from 2016 on take part: matching old scans by look alone found different places that look alike. Often it's a younger sibling in the same spot years later. *Same person* pairs photos where Photos names the same person, back to 2009. Not built: same-spot pairs with an old scan (they'd need a place).
- Date detective: Play → Date Detective and `photosearch dates` date the photos with a placeholder date, a group at a time, from album names, album series, people and look-alikes. 851 of 1,042 are dated (the rest are small loose groups). Look-alikes turned out a weak clue (25 of 105 years right when the whole event is hidden). Not built: Apple's labels as a month clue.
- Real video search: `photosearch videos` embeds each video's sound (10 s pieces) and a frame every 3 s, and a search ranks a video by its best moment ("🔊 heard at 0:10"). Hovering flips through the frames. Sound matches were judged by ear to set `SOUND_AT`: Happy Birthday, laughing, clapping and music come up by sound; "a dog barking" finds kids shouting.
- Clutter and sensitive-photo sweep: Albums → Tidy up → Clutter and private photos lists IDs and cards, screenshots, receipts and papers, and accidental shots, and sends a kind to its own album in Photos. Accidental shots turned out hard: blur and darkness also find dim family photos, so only the clearest (floors, black frames) count. Sending isn't tried on my library yet (bd7a318).
- `photosearch eval`: compares two variants of the index (vision tokens, shorter or compressed vectors, another index), with blind sheets to judge. It reproduced the vision-token numbers (de6e9da).
- Vision tokens judged by eye: 70 is 4.7× faster and only slightly worse (552f91d).
- Writing to the main library tested: `album` from the terminal, `make_album` through Claude, Copy to Photos and Send the extras.
