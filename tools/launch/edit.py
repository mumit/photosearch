"""Cuts the launch video from the takes: the web app (the director's take), then Claude making an album (sped up, with
the album appearing in Photos beside it), then an end card. Also a 9:16 cut of the same footage and a GIF per section.

    PHOTOSEARCH_DATA=data-demo uv run python tools/launch/edit.py

Reads, from data-demo/launch/: web.mp4 and web.beats.json (tools/director/director.py), claude-take.mp4 and
photos-album.mov (claude_take.py). Writes launch.mp4, launch-vertical.mp4 and gifs/ there. The words on screen are
below. Where to cut comes from the takes themselves: the web part ends where the storyboard's "end" beat starts, and
Claude is done at the last big change on the terminal.
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path

from common import OUT, PROMPT, demo_only

FONT = "/System/Library/Fonts/SFNS.ttf"
SPEED = 8  # Claude's searching and looking, sped up
TITLE, TAGLINE, SMALL, REPO = ("photosearch", "Search your photos by what’s in them", "open source · runs on your Mac",
                               "github.com/mumit/photosearch")
ASK = ("Or just ask Claude", ["photosearch is also an MCP server,", "so Claude Code can search, look,",
                              "and make albums for you."])
ASK_SHORT = "photosearch is also an MCP server for Claude Code"  # the 9:16 cut has less room
DONE = ("…and it’s in Photos", "{n} hikes, each one looked at first.")
# one GIF per section of the web take: (file, first beat, the beat it ends at, frames a second, width)
GIFS = [("1-search", "type", "open", 15, 800), ("2-lookalikes", "open", "galaxy", 15, 800),
        ("3-galaxy", "galaxy", "math", 12, 720), ("4-math", "math", "map", 15, 800), ("5-map", "map", "end", 15, 800)]

BG, TERM_BG = (14, 13, 12), (30, 30, 46)  # the page's dark theme; the terminal's (Catppuccin Mocha)
FG, SUB, GREY, ACCENT = (255, 255, 255), (186, 194, 222), (170, 170, 170), (245, 180, 60)
ENC = ["-r", "60", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-an"]


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True, check=True).stdout)


def font(size, weight=600):
    from PIL import ImageFont
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_axes([100, max(17, min(96, size)), 400, weight])  # width, optical size, grade, weight
    return f


class Card:
    """A frame of words, drawn with PIL: transparent, or on a background colour."""
    def __init__(self, w, h, bg=None):
        from PIL import Image, ImageDraw
        self.w, self.im = w, Image.new("RGBA" if bg is None else "RGB", (w, h), (0, 0, 0, 0) if bg is None else bg)
        self.d = ImageDraw.Draw(self.im)

    def text(self, x, y, s, size, weight=600, fill=FG):
        f = font(size, weight)
        self.d.text(((self.w - self.d.textlength(s, font=f)) / 2 if x is None else x, y), s, font=f, fill=fill)
        return self

    def badge(self, x, y, s, size=30):
        f = font(size, 700)
        w = self.d.textlength(s, font=f)
        x = (self.w - w - 40) / 2 if x is None else x
        self.d.rounded_rectangle((x, y, x + w + 40, y + size + 24), radius=(size + 24) // 2, fill=ACCENT)
        self.d.text((x + 20, y + 9), s, font=f, fill=(20, 20, 20))
        return self

    def save(self, path):
        self.im.save(path)
        return path


def claude_done(take):
    """When Claude's answer appears: the last big change on the terminal (after it, only the spinner and the clock)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(take), "-vf", "select='gt(scene,0.002)',showinfo", "-f",
                        "null", "-"], capture_output=True, text=True)
    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    if not times:
        sys.exit("can't find where Claude finished in claude-take.mp4")
    return times[-1]


def window_box(mov, tmp):
    """(w, h, x, y) of the window inside its recorded shadow."""
    import numpy as np
    from PIL import Image
    ff("-ss", min(4, duration(mov) / 2), "-i", mov, "-frames:v", 1, tmp / "win.png")
    a = np.asarray(Image.open(tmp / "win.png").convert("L")).astype(int) > 12
    rows, cols = np.where(a.mean(1) > 0.5)[0], np.where(a.mean(0) > 0.5)[0]
    return cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1, cols[0], rows[0]


def rounded(w, h, r, path):
    from PIL import Image, ImageDraw
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    m.save(path)
    return path


def main():
    demo_only()
    web, take, album = OUT / "web.mp4", OUT / "claude-take.mp4", OUT / "photos-album.mov"
    for f in (web, web.with_suffix(".beats.json"), take, album):
        if not f.exists():
            sys.exit(f"missing {f}: see tools/launch/README.md")
    beats = json.loads(web.with_suffix(".beats.json").read_text())
    n = len(json.loads((OUT / "album.json").read_text())) if (OUT / "album.json").exists() else 0
    cut = beats["end"]                      # the web take's own end card is replaced by ours
    typed = 1.5 + len(PROMPT) * 0.055 + 0.8  # the tape: a pause, the prompt at 55 ms a key, a pause, Enter
    done = claude_done(take)
    answer = min(done + 0.9, duration(take) - 0.1)  # the frame the answer holds on
    fast = (done - typed) / SPEED
    print(f"web 0-{cut:.1f}s · Claude typed by {typed:.1f}s, done at {done:.1f}s ({fast:.1f}s at {SPEED}×)")

    with tempfile.TemporaryDirectory(prefix="launch-") as t:
        t = Path(t)
        ww, wh, wx, wy = window_box(album, t)
        crop = f"crop={ww}:{wh}:{wx}:{wy}"

        # 16:9: the terminal on the left, words (and then the Photos window) on the right
        bg = Card(1920, 1080, TERM_BG).save(t / "bg.png")
        ask = Card(1920, 1080).text(1100, 110, ASK[0], 56, 700)
        for i, line in enumerate(ASK[1]):
            ask.text(1100, 196 + 46 * i, line, 32, 450, SUB)
        ask.save(t / "ask.png")
        ask.badge(1100, 360, f"{SPEED}× speed").save(t / "fast.png")
        Card(1920, 1080).text(1100, 110, DONE[0], 56, 700).text(1100, 196, DONE[1].format(n=n), 32, 450, SUB).save(t / "done.png")
        end = Card(1920, 1080, BG).text(None, 370, TITLE, 112, 700).text(None, 535, TAGLINE, 46, 500, (225, 225, 225))
        end.text(None, 605, SMALL, 36, 450, GREY).text(None, 715, REPO, 40, 600, ACCENT).save(t / "end.png")
        sw = 780

        def claude(prefix, bgs, term_xy, win_xy, win_w, answer_crop=""):
            """The three Claude parts: typing (1×), working (sped up), the answer with the album beside it (or below:
            answer_crop keeps only the top of the terminal, to make room)."""
            ask_png, fast_png, done_png = bgs
            tx, ty = term_xy
            ff("-loop", 1, "-i", ask_png, "-i", take, "-filter_complex",
               f"[1:v]trim=0:{typed},setpts=PTS-STARTPTS,fps=60[t];[0:v][t]overlay={tx}:{ty}:shortest=1,"
               "fade=in:st=0:d=0.4", "-t", typed, *ENC, t / f"{prefix}a.mp4")
            ff("-loop", 1, "-i", fast_png, "-i", take, "-filter_complex",
               f"[1:v]trim={typed}:{done},setpts=(PTS-STARTPTS)/{SPEED},fps=60[t];[0:v][t]overlay={tx}:{ty}:shortest=1",
               "-t", fast, *ENC, t / f"{prefix}b.mp4")
            wh_ = round(win_w * wh / ww)
            rounded(win_w, wh_, 14, t / f"{prefix}mask.png")
            ff("-loop", 1, "-i", done_png, "-ss", answer, "-i", take, "-i", album, "-loop", 1, "-i", t / f"{prefix}mask.png",
               "-filter_complex",
               f"[1:v]trim=end_frame=1,loop=-1:1,setpts=N/25/TB,fps=60{answer_crop}[t];[0:v][t]overlay={tx}:{ty}[a];"
               f"[2:v]fps=60,{crop},scale={win_w}:{wh_},format=rgba[w];[3:v]format=gray,fps=60[m];"
               f"[w][m]alphamerge,fade=in:st=0.3:d=0.5:alpha=1[p];[a][p]overlay={win_xy[0]}:{win_xy[1]}",
               "-t", 6.5, *ENC, t / f"{prefix}c.mp4")
            return [t / f"{prefix}{p}.mp4" for p in "abc"]

        def layer(png, bg_png, path):  # a transparent card over a background, as one image
            from PIL import Image
            Image.alpha_composite(Image.open(bg_png).convert("RGBA"), Image.open(png)).convert("RGB").save(path)
            return path

        ff("-i", web, "-t", cut, "-vf", f"fade=out:st={cut - 0.4}:d=0.4", *ENC, t / "w.mp4")
        parts = claude("h", [layer(t / f"{p}.png", bg, t / f"h{p}.png") for p in ("ask", "fast", "done")],
                       (60, 0), (1100, 300), sw)
        ff("-loop", 1, "-i", t / "end.png", "-vf", "fade=in:st=0:d=0.5", "-t", 4, *ENC, t / "e.mp4")
        concat(t, [t / "w.mp4", *parts, t / "e.mp4"], OUT / "launch.mp4")

        # 9:16: the web take between the name and the link; the terminal above the album
        Card(1080, 1920, BG).text(None, 330, TITLE, 84, 700).text(None, 450, TAGLINE, 40, 500, (225, 225, 225)) \
            .text(None, 1380, SMALL, 34, 450, GREY).text(None, 1440, REPO, 36, 600, ACCENT).save(t / "vweb.png")
        def vcard(name, title, sub, badge=None):
            c = Card(1080, 1920, TERM_BG).text(None, 90, title, 64, 700).text(None, 180, sub, 34, 450, SUB)
            return (c.badge(None, 1360, badge, 32) if badge else c).save(t / f"v{name}.png")
        vbgs = [vcard("ask", ASK[0], ASK_SHORT), vcard("fast", ASK[0], ASK_SHORT, f"{SPEED}× speed"),
                vcard("done", DONE[0], DONE[1].format(n=n).rstrip("."))]
        ff("-loop", 1, "-i", t / "vweb.png", "-i", t / "w.mp4", "-filter_complex",
           "[1:v]scale=1080:608:flags=lanczos[v];[0:v][v]overlay=0:656:shortest=1", *ENC, t / "vw.mp4")
        vparts = claude("v", vbgs, (40, 260), (40, 1160), 1000, answer_crop=",crop=1000:820:0:0")
        Card(1080, 1920, BG).text(None, 700, TITLE, 120, 700).text(None, 870, TAGLINE, 44, 500, (225, 225, 225)) \
            .text(None, 940, SMALL, 36, 450, GREY).text(None, 1060, REPO, 42, 600, ACCENT).save(t / "vend.png")
        ff("-loop", 1, "-i", t / "vend.png", "-vf", "fade=in:st=0:d=0.5", "-t", 4, *ENC, t / "ve.mp4")
        concat(t, [t / "vw.mp4", *vparts, t / "ve.mp4"], OUT / "launch-vertical.mp4")

        # GIFs: each section of the web take, and Claude's part (sped up, then the album)
        gifs = OUT / "gifs"
        gifs.mkdir(exist_ok=True)
        pal = ("split[a][b];[a]palettegen=stats_mode=diff:max_colors=200[p];"
               "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
        for name, a, b, fps, w in GIFS:
            ff("-ss", beats[a], "-t", beats[b] - beats[a] - 0.1, "-i", web, "-vf",
               f"fps={fps},scale={w}:-1:flags=lanczos,{pal}", gifs / f"{name}.gif")
        ff("-i", parts[1], "-i", parts[2], "-filter_complex",
           f"[0:v][1:v]concat=n=2:v=1,fps=12,scale=800:-1:flags=lanczos,{pal}", gifs / "6-claude.gif")
    for f in [OUT / "launch.mp4", OUT / "launch-vertical.mp4", *sorted((OUT / "gifs").glob("*.gif"))]:
        print(f"  {f.relative_to(OUT.parent)}  {duration(f):5.1f}s  {f.stat().st_size / 1e6:4.1f} MB")


def concat(t, parts, out):
    lst = t / f"{out.stem}.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", "-movflags", "+faststart", out)


if __name__ == "__main__":
    main()
