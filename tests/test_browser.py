"""Every view of the web page in headless Chrome, at desktop and phone size, against the made-up library: no JavaScript
errors, nothing wider than the screen. Slow (a few minutes) and needs Chrome and the internet (map tiles, the
libraries the page loads), so it only runs when asked:

    uv run pytest -m browser                          # PHOTOSEARCH_SHOTS=dir also saves a screenshot of every step
"""
import asyncio, base64, json, os, shutil, subprocess, tempfile, time, urllib.request
from pathlib import Path

import numpy as np
import pytest

from photosearch import why
from library import axis, noise, unit
from server import Server, free_port

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
pytestmark = [pytest.mark.browser, pytest.mark.skipif(not Path(CHROME).exists(), reason="needs Google Chrome")]

# throws, so the step fails, unless this element is on top all over the screen (a 5 x 5 grid of points)
ON_TOP = ("for (let i = 1; i < 6; i++) for (let j = 1; j < 6; j++) {{ const e = document.elementFromPoint(innerWidth * i / 6, innerHeight * j / 6); "
          "if (!e?.closest('#{}')) throw new Error('covered by ' + e?.tagName + '#' + e?.id + '.' + e?.className) }}")


def beach_corner(im):
    """The fake model's squares for Why?: a beach in the top left corner of every photo."""
    rng = np.random.default_rng(5)
    T = np.stack([unit(noise(rng, 1)) for _ in range(24)])
    for i in (0, 1, 6, 7):
        T[i] = unit(axis("beach") + 0.3 * T[i])
    return T, 6, 4


# (name, JavaScript to run, seconds to wait after)
STEPS = [
    ("home", "", 5),
    ("home-scroll", "scrollTo(0, 700)", 1),
    ("home-people", "document.getElementById('peopleshelf').scrollIntoView({block:'center'})", 1),
    ("home-cal", "document.getElementById('calbox').scrollIntoView({block:'center'})", 1),
    ("cal-hover", "[...document.querySelectorAll('.calg i[style]')].at(-2).dispatchEvent(new PointerEvent('pointerover',{bubbles:true}))", 1),
    ("day", "[...document.querySelectorAll('.calg i[style]')].at(-2).click()", 3),
    ("suggest", "scrollTo(0,0); const q=document.getElementById('q'); q.focus(); q.value='sa'; q.dispatchEvent(new Event('input'))", 2),
    ("search", "document.getElementById('sugg').classList.remove('on'); location.hash='search/'+encodeURIComponent('sunset at the beach')", 3),
    ("by-date", "document.querySelector('.seg [data-s=date]').click()", 1),
    ("lightbox", "document.querySelector('.seg [data-s=best]').click(); document.querySelector('#grid .tile').click()", 3),
    ("why", "document.getElementById('lbwhy').click()", 2),
    ("why-shown", "if (!document.querySelector('#whypanel .wsees span') || !document.querySelector('#whypanel .wrow')) throw new Error('no why panel'); "
                  "if (!document.getElementById('lbimg').style.webkitMaskImage) throw new Error('no heat map')", 0),
    ("wander", "document.querySelector('#lbsims img').click()", 3),
    ("wander-no-why", "if (!document.getElementById('lbwhy').hidden || !document.getElementById('whypanel').hidden) throw new Error('why on a look-alike')", 0),
    ("love-who", "localStorage.removeItem('who'); document.getElementById('lbpick').click()", 2),
    ("love", "if (document.getElementById('lbwho').hidden) throw new Error('no who chooser'); "
             "document.getElementById('lbwhoi').value='Sam'; document.getElementById('lbwho').requestSubmit()", 2),
    ("loved", "if (!document.getElementById('lbpick').classList.contains('on') || !document.getElementById('lbpick').textContent.includes('Sam')) "
              "throw new Error('not loved: ' + document.getElementById('lbpick').textContent)", 0),
    ("filtered", "lbOff(); location.hash='search/?person=Sam'", 3),
    ("filters", "document.getElementById('ftoggle').click()", 1),
    ("person", "closePanel(); location.hash='person/Sam'", 3),
    ("person-scroll", "scrollTo(0, 650)", 1),
    ("lightbox-day", "scrollTo(0,0); document.querySelector('#pyears .tile').click(); setTimeout(()=>document.querySelector('#lbmode [data-w=day]').click(), 800)", 3),
    ("world", "lbOff(); location.hash='world'", 5),
    ("world-region", "document.querySelector('#wregions [data-k=\"1\"]').click()", 3),
    ("world-sheet", "const c=[...WM.cells].sort((a,b)=>b.n-a.n)[0]; openPlace({cells:[c], n:c.n, head:c})", 3),
    ("world-photo", "document.querySelector('#wgrid .tile').click()", 2),
    ("world-photo-top", ON_TOP.format("lb"), 0),  # the map once covered photos opened from it
    ("world-slideshow", "lbOff(); document.getElementById('wplay').click()", 3),
    ("world-slideshow-top", ON_TOP.format("frame") + "; closeFrame()", 1),
    ("galaxy", "location.hash='galaxy/beach'", 12),
    ("galaxy-grow", "document.getElementById('gplay').click()", 4),
    ("galaxy-person", "stopGrow(); setUpto(null); location.hash='galaxy/?person=Sam'", 3),
    ("time-empty", "location.hash='time'", 2),
    ("time", "location.hash='time/birthday%20cake'", 4),
    ("time-person", "location.hash='time/?person=Alex'", 4),
    ("time-flip", "document.querySelector('#tspeed [data-v=flip]').click(); document.getElementById('tplay').click()", 2),
    ("time-who", "stopPlay(); document.getElementById('twho').click()", 1),
    ("play", "location.hash='play'", 2),
    ("players", "for (const n of ['Ana','Ben']) { document.getElementById('pname').value=n; document.getElementById('addp').requestSubmit(); }", 1),
    ("game-first", "document.querySelector('.card[data-mode=first]').click()", 4),
    ("game-reveal", "document.querySelector('.pair figure').click()", 2),
    ("game-year", "localStorage.removeItem('players'); playMenu(); document.querySelector('.card[data-mode=year]').click()", 3),
    ("detective", "playMenu(); document.getElementById('detcard').click()", 2),
    ("thennow", "playMenu(); document.getElementById('tncard').click()", 3),
    ("thennow-next", "document.getElementById('tnnext')?.click()", 2),
    ("thennow-person", "document.querySelector('#tnby [data-by=person]').click()", 3),
    ("recreate", "playMenu(); document.getElementById('rccard').click()", 3),
    ("recreate-pick", "document.querySelector('.rcadd')?.click()", 2),
    ("recreate-todo", "document.querySelector('#rctabs [data-t=todo]').click()", 2),
    ("math", "location.hash='math'; document.getElementById('mtext').value='a street'; document.getElementById('mplus').value='snow'; runMath()", 3),
    ("search-more", "location.hash='search/'+encodeURIComponent('a photo'); setTimeout(()=>document.getElementById('morebtn')?.click(), 2000)", 4),
    ("frame", "document.getElementById('rshow').click()", 3),
    ("frame-ambient", "closeFrame(); location.hash='frame'", 3),
    ("frame-pick", "setTimeout(()=>document.getElementById('fsrc').click(), 500)", 2),
    ("frame-person", "location.hash='frame/?person=Sam'", 3),
    ("frame-picks", "location.hash='frame/?picks=1'", 3),
    ("frame-picks-by", "if (!document.getElementById('fby').textContent.includes('Sam')) throw new Error('no picker in the frame')", 0),
    ("home-picks", "location.hash='home'; setTimeout(()=>document.getElementById('pickbox').scrollIntoView({block:'center'}), 1500)", 3),
    ("home-picks-shown", "if (document.getElementById('pickbox').hidden || !document.querySelector('#pickshelf .tile')) throw new Error('no family picks on home')", 0),
    ("keys", "closeFrame(); setTimeout(()=>dispatchEvent(new KeyboardEvent('keydown',{key:'?'})), 800)", 2),
    ("stories", "dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})); location.hash='stories'", 3),
    ("edit", "location.hash='edit/trip-2025-03-10'", 4),
    ("albums", "location.hash='albums'", 3),
    ("clutter", "location.hash='clutter'", 3),
    ("clutter-papers", "document.querySelector('#clukinds [data-k=papers]').click()", 2),
    ("album-search", "location.hash='search/beach'", 3),
    ("album-new", "document.querySelector('#racts a[href^=\"#album/new\"]').click()", 4),
    ("album-teach", "document.querySelector('#albgrid .tile .tacts [data-a=out]').click()", 3),
    ("album-strict", "const r=document.getElementById('albn'); r.value=5; r.dispatchEvent(new Event('input'))", 2),
    ("album-miss", "document.getElementById('albmiss').scrollIntoView()", 1),
    ("album-create", "scrollTo(0,0); document.getElementById('albsave').click()", 3),
    ("albums-list", "location.hash='albums'", 3),
    ("cleanup", "location.hash='cleanup'", 4),
    ("cleanup-keep", "document.querySelector('.clg figure:not(.keep)').click()", 2),
    ("cleanup-similar", "document.querySelector('#cllevel [data-l=similar]').click()", 3),
    ("phone", "location.hash='home'; setTimeout(()=>document.getElementById('phonebtn').click(), 1500)", 3),
]

OVERFLOW = """document.documentElement.scrollWidth > innerWidth + 1 ? [...document.querySelectorAll('body *')].filter(e => {
  const r = e.getBoundingClientRect();
  return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('.shelf,#strip,#lbsims,.strip,#fchips');
}).slice(0, 4).map(e => e.tagName + '#' + e.id + '.' + e.className) : null"""


def tour(url, width, height, phone, shots=None):
    """Problems found, as text: [] when every step was clean."""
    import websockets
    port, profile = free_port(), tempfile.mkdtemp(prefix="photosearch-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", f"--remote-debugging-port={port}",
                               f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems = []
    try:
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
            except OSError:
                time.sleep(0.1)
        ws_url = next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]

        async def run():
            async with websockets.connect(ws_url, max_size=80_000_000) as ws:
                n, step = 0, "load"

                async def cmd(method, **params):
                    nonlocal n; n += 1; i = n
                    await ws.send(json.dumps(dict(id=i, method=method, params=params)))
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("method") == "Runtime.exceptionThrown":
                            d = m["params"]["exceptionDetails"]
                            problems.append(f"{step}: JS error {d.get('exception', {}).get('description', d.get('text'))}")
                        if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
                            problems.append(f"{step}: console.error {[a.get('value', a.get('description')) for a in m['params']['args']]}")
                        if m.get("id") == i:
                            return m.get("result", m)

                async def ev(js):
                    r = await cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
                    if "exceptionDetails" in r:
                        problems.append(f"{step}: step failed: {r['exceptionDetails'].get('exception', {}).get('description', '')[:200]}")
                    return r.get("result", {}).get("value")

                await cmd("Runtime.enable")
                await cmd("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2 if phone else 1, mobile=phone)
                if phone:
                    await cmd("Emulation.setTouchEmulationEnabled", enabled=True)
                await cmd("Page.navigate", url=url)
                for step, js, wait in STEPS:
                    if js:
                        await ev(f"{{ {js}; 1 }}")
                    await asyncio.sleep(wait)
                    if over := await ev(OVERFLOW):
                        problems.append(f"{step}: wider than the screen: {over}")
                    if (iw := await ev("innerWidth")) != width:
                        problems.append(f"{step}: the page widened the viewport to {iw}")
                    if shots:
                        s = await cmd("Page.captureScreenshot", format="jpeg", quality=70)
                        Path(shots, f"{width}-{step}.jpg").write_bytes(base64.b64decode(s["data"]))
        asyncio.run(run())
    finally:
        chrome.kill(); chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)
    return problems


@pytest.mark.parametrize("width, height, phone", [(1440, 900, False), (390, 844, True)], ids=["desktop", "phone"])
def test_tour(monkeypatch, width, height, phone):
    shots = os.environ.get("PHOTOSEARCH_SHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(why, "tokens", beach_corner)
    monkeypatch.setattr(why, "COMMON", 0)  # the made-up library has too few labels to leave out the common ones
    s = Server(monkeypatch)
    try:
        problems = tour(f"http://localhost:{s.port}/", width, height, phone, shots)
        assert not problems, "\n".join(problems)
    finally:
        s.close()
