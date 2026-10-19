# Findings and learnings

What the experiments on photosearch found, how each setting in the code was chosen, and when to measure again.
[README.md](README.md) says how to use the app; this file says why it works the way it does.

Everything here was measured on one library: about 17,000 items (16,200 photos, 750 videos), on an M3 MacBook. Most
judging by eye was done blind by one judge (Claude), so small differences are within what a second judging would
move. New experiments go through `photosearch eval` (README → Experiments) and get a section here.

## Lessons that keep coming back

1. **Agreement isn't quality.** A change can reorder results a lot and still find photos that fit as well. 70
   vision tokens changed the first photo in more than half of searches but was only slightly worse by eye. Searches
   in Hindi shared only 10 to 16 of the first 24 with English, yet fit better. So judge the photos, blind, as well
   as counting overlap.
2. **Some things score high against everything. Subtract a baseline.** A loud video clip, a patch of sky and a quick
   vector all sit close to *any* words, so their raw scores flatter them. The fix that worked each time: score by how
   much closer something is to the search than to everyday descriptions (`SOUND_BASE` for sound, `BASE` for Why, the
   app's own search words for quick vectors). A general penalty learned from Apple's labels (CSLS) made things worse.
3. **Each search's scores sit at their own level.** No single score splits right from wrong across searches: a wrong
   sound for "a baby crying" scored higher than a right one for "music playing". Cut-offs are compromises, set where
   most right ones stay in the first page.
4. **Set cut-offs from marked examples, not from 0.5.** `SOUND_AT` was set by ear, `FOCUS` and Then and Now's
   thresholds by eye, and the Jev model's yes/no cut-offs (0.7 to 0.85) on labelled queries.
5. **Brute force is fine at this size.** All vectors are 52 MB and a search over them takes 0.6 ms in NumPy. No
   vector database, no compression.
6. **Vectors from different settings don't mix.** The index refuses other models and vision tokens. The one exception,
   the quick first index, needs a correction to mix fairly.

## Speed

| Setup | Photos/s | Full library |
|---|---|---|
| PyTorch MPS bf16, 280 vision tokens (default) | ~2.0 | 2 h 20 min (16,927 photos, measured) |
| PyTorch MPS bf16, 70 vision tokens | ~9 | ~30 min (estimated from 2,000 photos) |
| MLX (`mlx-community/embeddinggemma-2-bf16` via mlx-vlm) | ~1.3 | no gain, dropped |
| CPU fp32 | ~0.3 | — |

Videos take about 6 s each, mostly for the frames.

## Vision tokens (70 against 280)

The model cuts a photo into squares ("vision tokens"). 280 is the default; 70 is 4.7× faster.

On 2,000 random photos, the 70-token vectors have mean cosine 0.95 to the 280-token ones (5% are below 0.91, the
lowest 0.73). Over 50 searches of those 2,000:

| 70 tokens vs. 280 | Result |
|---|---|
| Same photo first | 22 of 50 searches |
| 280's first photo still in 70's top 5 | 45 of 50 |
| Top 10 in common | 6.4 on average |
| First 24 (one page) in common | 16.5 on average |

Judged by eye, blind: at 280 tokens, 194 of the 250 photos fit the search; at 70, 187. Where the first photo
differed (28 searches), it was about as good in 22, better at 280 in 4 and better at 70 in 2. Judging the same
sample again in a new blind order gave 192 and 185, and the same 4, 2 and 22.

**Decision:** 280 stays the default. 70 mostly reorders results and is only slightly worse, which is why the quick
first index uses it.

## Quick first index (`index --quick`)

`index --quick` reads photos at 70 tokens (about 9 a second against 2), then the next plain `index` redoes them at
280, newest first. Until then, the index holds a mix.

**The problem.** A 70-token vector scores 0.019 higher against words than the same photo's 280-token one. Small, but
search ranks by small differences: with a quarter of photos still quick, they took half of each search's first 24.

**The fix.** Each quick vector is moved back along the direction the app's own words share (`quick_shift()` in
`index.py`, from the interest words plus a few everyday ones), by the 0.019 gap. Measured on 2,000 photos, with the
fix set on 1,000 photos and 25 searches and tested on the rest:

| Still quick | First 24 the same as an all-280 index, with the fix | without |
|---|---|---|
| a quarter | 21.8 | 18.4 |
| half | 19.5 | 15.8 |
| three quarters | 18.2 | 15.6 |

With the fix, quick photos take their fair share of the first 24.

**What didn't win.** Subtracting the gap from search scores worked as well for search, but not for features that
compare photos with photos (the time machine, smart albums, look-alikes). Fixing the vectors covers all of them. A
least-squares map from 70 to 280 overfit and made things worse.

**Measure again** with a new model, or if `QUICK_TOKENS` changes.

## Shorter or compressed vectors

Same sample and searches as vision tokens:

| Variant | Same first photo | First 24 in common |
|---|---|---|
| int8 | 49 of 50 | 23.1 |
| 256 numbers | 27 of 50 | 18.4 |
| 1 bit per number | 24 of 50 | 14.4 |
| 128 numbers | 21 of 50 | 11.6 |
| 1 bit, then the best 100 rescored with full vectors | 49 of 50 | |

**Decision:** none is used, since search is already fast (lesson 5). int8, or 1 bit with rescoring, is the path if a
library ever gets 10× bigger. The "photo anchor" published by pastel-labs on Hugging Face only matters for 1- or
4-bit vectors.

## Searches in other languages

24 searches in Spanish, French, Hindi, Chinese, Arabic and Bengali, over the whole library, judged blind against the
English ones (the top 5 of all seven in random order). Photos that fit, of 120:

| Hindi | Chinese | English | French | Spanish | Arabic | Bengali |
|---|---|---|---|---|---|---|
| 104 | 102 | 94 | 93 | 92 | 91 | 88 |

So search works in any of them, with no change. The results differ from English (10 to 16 of the first 24 in common)
but fit as well. Bengali was the weakest, on mountains, group photos, trains and babies. The gaps between the first
six are within what a second judging would move.

## Sound in videos (`SOUND_BASE` and `SOUND_AT`)

`photosearch videos` cuts each video's sound into 10-second pieces, and the model turns each piece into a vector in
the same space as text. A video ranks by its best moment: its poster, a later frame, or a piece of sound. Frames
score exactly like photos. Sound needs two corrections.

**`SOUND_BASE`: take away the head start of loud clips.** A trampoline park or a stadium scores fairly high against
*every* search, so raw sound scores put noisy videos everywhere. `SOUND_BASE` is a list of everyday home-video
sounds ("people talking", "background noise", "voices", "a room"…). Each piece of sound gets a baseline, its average
closeness to that list, and scores by how far above it your search is:

> margin = (sound vs. search) − (sound vs. everyday sounds)

A clip now scores well only when it sounds like *your* words. On 50 videos, real matches stood out by +0.09 to +0.19
(Happy Birthday over a cake, laughing on a couch), and the rest by about 0.

**`SOUND_AT`: put sound on the photos' scale.** The margin is about 0.1, while good photo matches score 0.65 to
0.80. To rank them together, the app adds a constant:

> sound score = margin + `SOUND_AT` (0.59)

So `SOUND_AT` is the dial for how much sound shows up. Higher brings more videos by sound, wrong ones too; lower lets
only the clearest sounds in among the photos. For "people laughing", the 24th result scores 0.697, so a sound must
stand out by about 0.11 to reach the first page.

**How `SOUND_AT` was set.** By ear. For 12 searches ("people laughing", "a dog barking", "waves crashing on a beach"),
the sound matches ranked 1 to 4, 8 and 16 were played back in random order, without their scores, and each marked as
the searched sound, something else, or can't tell (`data/sound-marks.json`). Then each value of `SOUND_AT` was tried,
counting the right and wrong heard videos in each search's first 24:

| `SOUND_AT` | Right | Wrong |
|---|---|---|
| 0.59 (chosen) | 19 | 6, all "a dog barking" bringing up kids shouting |
| 0.62 (first guess) | 24 | 18 |

**What it hears, and what it doesn't.** Of 72 marked clips: 38 right, 33 wrong, 1 can't tell. Happy Birthday,
laughing, clapping, cheering and music come up well. The model hears the *kind* of sound more than its source: kids
shouting matched "a dog barking", singing matched "birds singing", a fairground ride matched "fireworks". The margin
told right from wrong only a little (0.62, where 0.5 is chance), because of lesson 3: "a baby crying" got six wrong
matches at +0.10 to +0.12, and "music playing" six right ones at +0.03 to +0.05. Scoring each sound against all sounds
for that search, or adding "children playing" to `SOUND_BASE`, didn't help.

**Other checks.** Spoken and made-up test sounds (a weather forecast, "happy birthday", beeps, noise) each scored
highest on their own description. Text and image vectors are the same with the audio encoder loaded or not. ✦ Looks
like this uses only frames, since a photo has no sound.

**Measure again** with a new model or a change to `SOUND_BASE`, since both move the margins. More videos don't.

## Why did this match (`why.py`)

**Where.** A photo's vector is the mean of its squares' vectors (a grid of about 19 × 14), so each square's score is
its exact share of the photo's score, from one pass of the model (0.5 s). As with sound, a square counts by how much
closer it is to the search than to everyday descriptions (`BASE`), because stray squares of sky scored high for
anything. Tested by covering the hottest quarter of 17 photos (6 searches) and measuring how far the score fell:

| Which quarter covered | Score fell by |
|---|---|
| hottest, against everyday descriptions (used) | 0.032 |
| hottest, by covering squares one at a time (16 s a photo) | 0.027 |
| hottest, by plain score | 0.025 |
| random | 0.002 |

**Whole scenes.** A search for a whole scene (a backyard, a pool) doesn't sit in any one part: 64-74% of the lit part
sits in the hottest quarter, against 80-92% for a dog or a balloon. So below `FOCUS` = 0.77 it says the whole scene
matches. Judged by eye on 20 searches: small, clear things light up well (a soccer ball, a lighthouse, a bowl of
noodles); a small dog in a group photo or an airplane wing don't.

**Which words.** Each word is left out in turn and the score compared. It was right each time it said a word didn't
fit (a balloon that was the sun, fishing with nobody fishing). A word counts as not fitting only when leaving it out raises the score by more
than 0.005 (`MISFIT`); smaller changes are noise.

**What it sees.** Photos' labels as words (those on 3+ photos, without the 40 most common, which fit everything): on
1,500 photos, one of its top five was among Photos' own labels for 71%, against 5% for the five most used labels.

## Then and Now

Judged by eye on sheets of the best pairs.

- **Same spot.** With GPS (within 150 m, 4+ years apart), pairs above 0.8 were nearly all the same spot. Matching by
  look alone found places that look alike instead (Angkor Wat and Teotihuacán, two different aquariums), so both
  photos need GPS. Above 0.97 a pair is one photo saved twice. Clutter (an ID shot twice, floors, price tags) is left
  out. 32 pairs on 16,000 photos; only photos from 2016 on have GPS here. The scene decides, not who's in it, so many
  are one child, then a younger sibling in the same spot.
- **Same person.** Pairs above 0.88, in photos with at most 2 named people, were nearly all good (45 pairs, from 2009
  on). Below that, or with more people named, they were parties: one face among many in a dining room that looks like
  every other.

## Recreate This

Ranking old photos of one or two named people by a few posing descriptions ("a child posing for the camera", "a
parent holding a baby, posing for a photo") found kid portraits and parent-with-baby shots. The general interest score
found busy scenes (a trampoline, a party) that can't be redone. Matching the new shot (0.80, then you confirm) isn't
measured yet: it needs a real recreation.

## Search, negation and the search box

- **Photos that match everything.** Some photos (very dark, very plain) score fairly high for any query. A CSLS-style
  penalty using Apple's labels as a query bank was tried on ~5k photos and made results worse (it boosted documents
  and handwriting), so search uses plain cosine.
- **Negation.** The model is weak at "no selfies" inside a query. `exclude` subtracts 0.5× the excluded text's vector
  from the query instead (as Photo Math does). On "group photos at a party" minus "a selfie" it removed the selfies;
  for "no people" in landscapes the plain query already worked.
- **Laya** (an open "System One" decision model) for parsing the search box, on 20 labelled queries: 20/20 on "wants no
  people" and "no selfies", but 12/20 photo-vs-video, 14/20 time period, 17/20 season, ~430 ms a query on CPU and
  ~1.5 GB. Not adopted: keyword rules beat it on the choice questions, and the **without…** field covers negation.
- **Jev** (TypeSafe's hosted System One model) on the same 20: 19/20 photo-vs-video, 20/20 time period, 18/20
  season, ~115 ms. Its yes/no answers needed cut-offs of 0.7 ("no people") and 0.85 ("no selfies"), not 0.5; on 20
  fresh queries with those it got 95/100. It powers the optional ✨ smart search. Choices under 60% confidence are
  ignored.

## Galaxy

UMAP with `min_dist=0.6`, so near-duplicates spread out instead of piling up, and k-means regions named by the Apple
labels most distinctive for each region.
