"""Cuts the photosearch launch video, the same way as the first one: the web take up to its
"end" beat, then Claude making an album (typing at 1x, working sped up, its answer with the album in Photos beside
it), then an end card. Also the README GIF (a moment from each feature), a GIF per section for posts, subtitles for
the web part, and a short cut of what's new since the first launch video.

    reshoot edit edit.py takes/web.mp4 takes/claude.mp4 [PHOTOS_ALBUM.mov [OUT_DIR]]

Inside `reshoot run` there is no Photos window yet (Claude makes the album during the run), so the answer is shown
on its own. finish.sh records the Photos window afterwards and runs this again with it. Writes photosearch.mp4,
photosearch-readme.gif, photosearch.srt, photosearch-new.mp4 and gifs/ to OUT_DIR (default: next to the web take).
"""
import json, sys, tempfile
from pathlib import Path

from reshoot import cut

# The words on screen
TITLE, TAGLINE, SMALL, REPO = ("photosearch", "Search your photos by what’s in them", "open source · runs on your Mac",
                               "github.com/mumit/photosearch")
ASK = ("Or just ask Claude", ["photosearch is also an MCP server,", "so Claude Code can search, look,",
                              "and make albums for you."])
DONE = ("…and it’s in Photos", "{n} hikes, each one looked at first.", "Each photo looked at first.")
PROMPT = ('Make an album called "Best hikes" from my photos: trails, forests and views from the top. No people, '
          "nothing blurry, so look at them before you add any.")  # as typed in claude.tape
SPEED = 8  # Claude's searching and looking, sped up
# The README GIF (docs/photosearch.gif): a moment from each feature, sped up, kept under 5 MB so GitHub shows it
# quickly. Each is (beat, seconds from it, beat, seconds from it, speed); then frames a second and width.
TOUR = [("search", -1.5, "open", -0.4, 1.6),      # the last words typed, then the results
        ("why", 0.6, "wander1", -0.8, 1.2),       # ? Why
        ("grow", 0, "light", 0, 4),               # the galaxy grows year by year
        ("light", 0.5, "math", -1.0, 1.6),        # a search lights it up
        ("math-go", 0.3, "to-map", -0.3, 1.5),    # photo math's answer
        ("map", 0, "to-play", -0.3, 2),           # the map flies to a region
        ("thennow", 0.3, "end", -0.3, 1)]         # then and now
GIF = (6, 640)
# one GIF per section of the web take, for posts: (file, first beat, the beat it ends at, frames a second, width)
GIFS = [("search", "type", "open", 15, 800), ("why", "open", "wander1", 15, 800),
        ("lookalikes", "wander1", "to-galaxy", 15, 800), ("galaxy", "galaxy", "math", 12, 720),
        ("math", "math", "to-map", 15, 800), ("map", "map", "to-play", 15, 800), ("thennow", "to-play", "end", 15, 800)]
# what's new since the first launch video: a title card, then these parts of the web take, then the end card
NEW = ("New in photosearch", "Why each photo matched · Then and Now", [("open", "wander1"), ("to-play", "end")])

W, H = 1920, 1080
BG, TERM_BG = (14, 13, 12), (30, 30, 46)  # the page's dark theme; the terminal's (Catppuccin Mocha)
SUB, GREY, ACCENT = (186, 194, 222), (170, 170, 170), (245, 180, 60)
TERM_XY, WIN_XY, WIN_W, TEXT_X = (60, 0), (1100, 300), 780, 1100


def main(web, claude, window=None, out=None):
    web, claude = Path(web), Path(claude)
    out = Path(out) if out else web.parent
    out.mkdir(parents=True, exist_ok=True)
    b = cut.beats(web)
    end = b["end"]  # the take's own end card is replaced by ours
    typed = 1.5 + len(PROMPT) * 0.055 + 0.8  # the tape: a pause, the prompt at 55 ms a key, a pause, Enter
    done = cut.last_change(claude)  # Claude's answer: after it only the spinner and the clock change
    answer = min(done + 0.9, cut.duration(claude) - 0.1)
    album = Path(window).with_name("album.json") if window else None
    n = len(json.loads(album.read_text())) if album and album.exists() else 0
    print(f"web 0-{end:.1f}s · Claude typed by {typed:.1f}s, done at {done:.1f}s "
          f"({(done - typed) / SPEED:.1f}s at {SPEED}x) · Photos window: {window or 'none'}")

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        ww, wh, _ = cut.probe(web)
        parts = [cut.trim(web, 0, end, t / "web-cut.mp4", fade_out=0.4)]
        if (ww, wh) != (W, H):  # a preview's smaller web take, brought up to the cut's size
            parts[0] = cut.place(cut.Card(W, H, BG).save(t / "black.png"), parts[0], 0, 0, t / "web.mp4", width=W)

        def card(name, title, lines, badge=None):
            c = cut.Card(W, H, TERM_BG).text(TEXT_X, 110, title, 56, 700)
            for i, line in enumerate(lines):
                c.text(TEXT_X, 196 + 46 * i, line, 32, 450, SUB)
            return (c.badge(TEXT_X, 360, badge) if badge else c).save(t / f"{name}.png")

        typing = cut.trim(claude, 0, typed, t / "typing.mp4", fade_in=0.4)
        parts.append(cut.place(card("ask", ASK[0], ASK[1]), typing, *TERM_XY, t / "ask.mp4"))
        working = cut.speed(claude, typed, done, SPEED, t / "working.mp4")
        parts.append(cut.place(card("fast", ASK[0], ASK[1], f"{SPEED}× speed"), working, *TERM_XY, t / "fast.mp4"))

        # The answer, held, with the album in Photos beside it
        from PIL import Image
        cut.ff("-ss", answer, "-i", claude, "-frames:v", 1, t / "answer.png")
        sub = DONE[1].format(n=n) if n else DONE[2]
        bg = Image.open(card("done", DONE[0], [sub])).convert("RGB")
        bg.paste(Image.open(t / "answer.png").convert("RGB"), TERM_XY)
        bg.save(t / "done-bg.png")
        if window:
            parts.append(cut.window_clip(window, t / "done-bg.png", *WIN_XY, t / "done.mp4", width=WIN_W))
        else:
            parts.append(cut.still(t / "done-bg.png", 6.5, t / "done.mp4", fade_in=0))

        c = cut.Card(W, H, BG).text(None, 370, TITLE, 112, 700).text(None, 535, TAGLINE, 46, 500, (225, 225, 225))
        c.text(None, 605, SMALL, 36, 450, GREY).text(None, 715, REPO, 40, 600, ACCENT)
        parts.append(cut.still(c.save(t / "end.png"), 4, t / "end.mp4"))
        cut.concat(parts, out / "photosearch.mp4")

        c = cut.Card(W, H, BG).text(None, 430, NEW[0], 96, 700).text(None, 575, NEW[1], 44, 500, (225, 225, 225))
        new = [cut.still(c.save(t / "new.png"), 2.5, t / "new.mp4")]
        for i, (a, z) in enumerate(NEW[2]):
            new.append(cut.trim(web, b[a], b[z], t / f"new{i}.mp4", fade_in=0.3, fade_out=0.3))
            if (ww, wh) != (W, H):
                new[-1] = cut.place(t / "black.png", new[-1], 0, 0, t / f"new{i}-big.mp4", width=W)
        cut.concat([*new, parts[-1]], out / "photosearch-new.mp4")
        gifs = out / "gifs"
        gifs.mkdir(exist_ok=True)
        for name, a, z, fps, width in GIFS:
            cut.gif(web, b[a], b[z] - 0.1, gifs / f"{name}.gif", fps=fps, width=width)
        claude_part = cut.concat(parts[-4:-1], t / "claude-part.mp4")  # working sped up, then the answer and album
        cut.gif(claude_part, cut.duration(parts[-4]), cut.duration(claude_part), gifs / "claude.gif", fps=12, width=800)

    cut.write_srt(cut.cues(web, 0, end), out / "photosearch.srt")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        tour = [cut.speed(web, b[a] + da, b[z] + dz, sp, t / f"tour{i}.mp4") if sp != 1 else
                cut.trim(web, b[a] + da, b[z] + dz, t / f"tour{i}.mp4") for i, (a, da, z, dz, sp) in enumerate(TOUR)]
        tour = cut.concat(tour, t / "tour.mp4")
        cut.gif(tour, 0, cut.duration(tour), out / "photosearch-readme.gif", fps=GIF[0], width=GIF[1])
    for f in [out / "photosearch.mp4", out / "photosearch-new.mp4", out / "photosearch-readme.gif",
              *sorted((out / "gifs").glob("*.gif"))]:
        print(f"  {f}  {cut.duration(f):5.1f}s  {f.stat().st_size / 1e6:4.1f} MB")


if __name__ == "__main__":
    main(*sys.argv[1:])
