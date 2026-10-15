"""Records the web page acting out a storyboard: headless Chrome, so nothing but the page is ever captured.

    uv run python tools/director/director.py STORYBOARD.py OUT.mp4 [--url http://localhost:8766/] [--size 1280x720@1.5]

A storyboard is a Python file with BEATS: a list of (name, JavaScript, seconds to hold afterwards), and optionally WARM:
views (#hashes) to open before recording, so their map tiles and data are already loaded when they're shown. The JavaScript runs
in the page as the body of an async function, with __demo (overlay.js) for the cursor, typing and captions. Every frame
Chrome paints is kept with its time, and ffmpeg turns them into a steady 60 fps video. Next to OUT.mp4 it writes
OUT.photos.json (every photo the page loaded, to check before sharing) and OUT.beats.json (when each beat starts).
"""
import argparse, asyncio, base64, json, runpy, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HERE = Path(__file__).resolve().parent


class Page:
    def __init__(self, ws, frames):
        self.ws, self.n, self.waiting, self.frames, self.errors, self.photos = ws, 0, {}, frames, [], set()
        self.beats = {}  # name: when the beat started (seconds since epoch, like the frames)

    async def read(self):
        try:
            await self._read()
        except websockets.ConnectionClosed:
            pass

    async def _read(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.waiting:
                self.waiting.pop(m["id"]).set_result(m)
            elif m.get("method") == "Page.screencastFrame":
                p = m["params"]
                self.frames.append((p["metadata"]["timestamp"], base64.b64decode(p["data"])))
                await self.ws.send(json.dumps(dict(id=0, method="Page.screencastFrameAck", params=dict(sessionId=p["sessionId"]))))
            elif m.get("method") == "Network.requestWillBeSent":  # every photo the page loads: what the video can show
                u = m["params"]["request"]["url"].split("?")[0]
                if "/thumb/" in u or "/photo/" in u:
                    self.photos.add(u.rsplit("/", 1)[1].removesuffix(".jpg"))
            elif m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                self.errors.append(d.get("exception", {}).get("description", d.get("text")))

    async def cmd(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiting[self.n] = fut
        await self.ws.send(json.dumps(dict(id=self.n, method=method, params=params)))
        m = await fut
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def run(self, js):
        r = await self.cmd("Runtime.evaluate", expression=f"(async () => {{ {js}\n }})()", awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "step failed"))
        return r.get("result", {}).get("value")


async def record(beats, url, w, h, dpr, frames, theme="dark", warm=()):
    port = 9400
    profile = tempfile.mkdtemp(prefix="director-")
    chrome = subprocess.Popen([CHROME, "--headless", "--hide-scrollbars", "--force-color-profile=srgb", "--mute-audio",
                               f"--remote-debugging-port={port}", f"--user-data-dir={profile}", f"--window-size={w},{h}",
                               "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        tabs = []
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
            except OSError:
                time.sleep(0.1)
        ws_url = next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=200_000_000) as ws:
            page = Page(ws, frames)
            reader = asyncio.create_task(page.read())
            await page.cmd("Page.enable"); await page.cmd("Runtime.enable"); await page.cmd("Network.enable")
            await page.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=False)
            await page.cmd("Emulation.setEmulatedMedia", features=[dict(name="prefers-color-scheme", value=theme)])
            await page.cmd("Page.navigate", url=url)
            await asyncio.sleep(4)  # fonts, the first photos
            for view in warm:
                await page.cmd("Runtime.evaluate", expression=f"location.hash = {json.dumps(view)}")
                await asyncio.sleep(4)
            if warm:
                await page.cmd("Runtime.evaluate", expression="location.hash = ''; scrollTo(0, 0)")
                await asyncio.sleep(2)
            # the page moves between views by #hash and never reloads, so the overlay goes in once
            await page.cmd("Runtime.evaluate", expression=(HERE / "overlay.js").read_text())
            if await page.run("return typeof __demo") != "object":
                raise RuntimeError("the overlay didn't load: " + "; ".join(page.errors))
            await page.cmd("Page.startScreencast", format="jpeg", quality=92, maxWidth=int(w * dpr), maxHeight=int(h * dpr))
            for name, js, hold in beats:
                t = page.beats[name] = time.time()
                if js:
                    await page.run(js)
                await asyncio.sleep(hold)
                print(f"  {name:22} {time.time() - t:5.1f}s", flush=True)
            frames.append((time.time(), None))  # when recording stopped: the last frame holds until here
            await page.cmd("Page.stopScreencast")
            await asyncio.sleep(0.3)
            reader.cancel()
            return page.errors, page.photos, page.beats
    finally:
        chrome.kill(); chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)


def encode(frames, out, fps=60, size="1920:1080"):
    """Each frame shown until the next was painted (Chrome only sends one when something changes, so a still page sends
    none), then resampled to a steady fps."""
    end = frames[-1][0] if frames and frames[-1][1] is None else None
    frames = [f for f in frames if f[1] is not None]
    tmp = Path(tempfile.mkdtemp(prefix="director-frames-"))
    try:
        lines = []
        for i, (t, jpg) in enumerate(frames):
            (tmp / f"{i:06}.jpg").write_bytes(jpg)
            nxt = frames[i + 1][0] if i + 1 < len(frames) else max(end or 0, t + 1 / fps)
            lines += [f"file '{tmp / f'{i:06}.jpg'}'", f"duration {max(nxt - t, 1 / 240):.5f}"]
        lines.append(f"file '{tmp / f'{len(frames) - 1:06}.jpg'}'")
        (tmp / "list.txt").write_text("\n".join(lines))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                        "-vf", f"fps={fps},scale={size}:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "slow",
                        "-crf", "17", "-movflags", "+faststart", str(out)], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("storyboard"); ap.add_argument("out")
    ap.add_argument("--url", default="http://localhost:8766/")
    ap.add_argument("--size", default="1280x720@1.5", help="CSS width x height @ device pixel ratio")
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    a = ap.parse_args()
    wh, dpr = a.size.split("@") if "@" in a.size else (a.size, "1")
    w, h = map(int, wh.split("x"))
    board = runpy.run_path(a.storyboard)
    beats = board["BEATS"]
    frames = []
    errors, photos, starts = asyncio.run(record(beats, a.url, w, h, float(dpr), frames, a.theme, board.get("WARM", ())))
    Path(a.out).with_suffix(".photos.json").write_text(json.dumps(sorted(photos)))  # for checking each one before sharing
    if frames:  # where each beat starts in the video, for cutting it up afterwards (tools/launch/edit.py)
        Path(a.out).with_suffix(".beats.json").write_text(json.dumps({n: round(t - frames[0][0], 3) for n, t in starts.items()}))
    if len(frames) < 3:
        sys.exit("no frames captured")
    span = frames[-1][0] - frames[0][0]
    gaps = sorted(b[0] - a_[0] for a_, b in zip(frames[:-1], frames[1:-1]))
    print(f"{len(frames)} frames over {span:.1f}s: {len(frames) / span:.0f} fps on average, "
          f"longest gap {gaps[-1] * 1000:.0f} ms, 95% of gaps under {gaps[int(len(gaps) * .95)] * 1000:.0f} ms")
    encode(frames, a.out, size=f"{int(w * float(dpr)) // 2 * 2}:{int(h * float(dpr)) // 2 * 2}")
    print("wrote", a.out, f"| {len(photos)} photos loaded (listed in {Path(a.out).with_suffix('.photos.json').name})",
          "| page errors:", errors or "none")


if __name__ == "__main__":
    main()
