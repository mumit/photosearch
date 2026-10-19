"""`photosearch serve`: the web page and its API."""
import json, re, sys, time
from datetime import date
from pathlib import Path

import numpy as np

from . import embed, photos_app, smartbox
from .config import DATA, LIBRARY, ROOT, THUMBS, WEB
from .store import ThreadCon, index_library, photo_info
from .images import photo_jpeg
from .search import SEASONS, best_of, search, similar
from .checks import CHECK_N, check
from .smartbox import parse_query
from .places import near, world
from .people import people, person
from .explore import days, galaxy, game_round, on_this_day, overview, photo_math, rediscover, timeline
from .stories import STORY_ID, edit_review, export_name, load_review, render_review, stories, story_candidates, story_for_editor, story_uuids
from .albums import album_preview, album_to_photos, album_view, albums, delete_album, save_album
from .dupes import DUP_LEVELS, dupes, dupes_choose, dupes_send
from .clutter import clutter, clutter_choose, clutter_send
from .dates import next_group, set_date, undo as undo_dates
from .thennow import then_and_now
from .picks import loved_by, pick, picks
from .recreate import ideas as recreate_ideas, post as recreate_post, recreations
from .videos import FRAMES, frame_list
from .why import explain, vocab
from .photos_app import Fetcher
from .lan import LOGIN, LanAccess

VIDEO_FRAME = re.compile(r"[0-9A-F-]{36}/\d{1,6}\.jpg")  # a frame kept by `photosearch videos`


def app_icon(px):
    """The app icon: the brand's colour wheel (amber, coral, violet, blue, green, as in the page's logo) around a dark
    lens. Drawn once, then cached."""
    f = DATA / f"icon-{px}.png"
    if not f.exists():
        from PIL import Image, ImageFilter
        stops = np.array([(242, 179, 61), (232, 102, 74), (143, 91, 214), (62, 143, 214), (79, 192, 141), (242, 179, 61)], float)
        y, x = np.mgrid[0:px, 0:px] / px - 0.5
        t = ((np.degrees(np.arctan2(y, x)) + 110) % 360) / 360 * (len(stops) - 1)
        i = np.floor(t).astype(int); w = (t - i)[..., None]
        rgb = stops[i] * (1 - w) + stops[np.minimum(i + 1, len(stops) - 1)] * w
        r = np.hypot(x, y)[..., None]
        rgb = rgb * (1.08 - 0.5 * np.clip(r - 0.3, 0, 1))  # a little darker towards the corners
        lens = r[..., 0] < 0.24
        rgb[lens] = (15, 14, 12)
        rgb[(r[..., 0] >= 0.24) & (r[..., 0] < 0.262)] = (246, 241, 232)
        hl = (np.hypot(x + 0.08, y + 0.08) < 0.035)  # a glint on the lens
        rgb[hl] = rgb[hl] * 0.75 + 255 * 0.25
        img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
        img.resize((px * 2, px * 2)).filter(ImageFilter.SMOOTH).resize((px, px), Image.LANCZOS).save(f)
    return f.read_bytes()


MANIFEST = json.dumps(dict(name="Photosearch", short_name="Photos", start_url="/", display="standalone", background_color="#0f0e0c",
                           theme_color="#0f0e0c", icons=[dict(src="/icon-192.png", sizes="192x192", type="image/png"),
                                                         dict(src="/icon-512.png", sizes="512x512", type="image/png", purpose="any maskable")]))


# The page's own files, by name: nothing else under web/ is served
STATIC = {"/app.css": "text/css; charset=utf-8"} | {f"/js/{f.name}": "text/javascript; charset=utf-8" for f in (WEB / "js").glob("*.js")}


def presenter_library(a):
    """`serve --demo`, for recording a demo: the name of the library it shows, or exits if this isn't a demo index.
    It must be a separate data folder (PHOTOSEARCH_DATA) built from a separate Photos library, never your own."""
    if a.lan:
        sys.exit("--demo is for recording on this Mac, so it doesn't go with --lan")
    if DATA.resolve() == (ROOT / "data").resolve():
        sys.exit("--demo needs a demo's data folder (PHOTOSEARCH_DATA=...): data/ is your own library's index")
    lib = index_library()
    if not lib:
        sys.exit(f"{DATA} doesn't record which Photos library it's of: run `photosearch index --library ...` for it")
    try:
        from osxphotos.utils import get_system_library_path
        system = get_system_library_path() or str(LIBRARY)
    except Exception:
        system = str(LIBRARY)
    if Path(lib).resolve() == Path(system).resolve():
        sys.exit(f"{DATA} is an index of your own library ({lib}), not a demo's")
    return Path(lib).stem


class Checked(list):
    """Search results, and whether Jev checked them (✨, checks.py)."""
    def __init__(self, items, checked):
        super().__init__(items); self.checked = checked


def cmd_serve(a):
    make_server(a).serve_forever()


def make_server(a):
    """The web server for `serve`'s arguments, listening but not yet answering (serve_forever does)."""
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    demo = presenter_library(a) if getattr(a, "demo", False) else None
    con = ThreadCon()
    lan = LanAccess(a.port, a.new_passcode) if a.lan else None
    allowed = {f"localhost:{a.port}", f"127.0.0.1:{a.port}"} | (lan.hosts if lan else set())
    embed.model()  # warm up before first request
    vocab(con)  # Photos' labels for the Why? panel: read by the model once (~30 s), then kept in the index
    fetcher = Fetcher(con)

    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]

    def api_search(q):
        f = dict(person=split(q.get("person")), after=q.get("after"), before=q.get("before"), kind=q.get("kind"),
                 place=q.get("place"), months=SEASONS.get(q.get("season")))
        k = int(q.get("k", 48))
        if "like" in q:
            return similar(con, q["like"], k, **f)
        if not q.get("q"):  # just filters, e.g. a person picked from the suggestions
            return best_of(con, k, **f)
        res = search(con, q["q"], max(k, CHECK_N) if q.get("check") else k, split(q.get("exclude")), **f)
        if q.get("check"):  # ✨ on: Jev checks the first photos (checks.py)
            res, done = check(con, q["q"], res)
            return Checked(res[:k], checked=done)
        return res

    def api_parse(q):  # the smart search box: {"enabled": False} when there's no Jev key
        if not smartbox.jev_key():
            return dict(enabled=False)
        if not q.get("q"):
            return dict(enabled=True)
        try:
            return dict(enabled=True, filters=parse_query(con, q["q"]))
        except Exception as ex:  # offline, bad key, rate limit: search still works without it
            return dict(enabled=True, error=f"{ex.__class__.__name__}: {ex}")

    def api_open(q):  # reveal in Photos via AppleScript (on this Mac's screen, so only for this Mac)
        import subprocess
        uuid = "".join(c for c in q["uuid"] if c.isalnum() or c in "-/")
        subprocess.run(["osascript", "-e", f'tell application "Photos" to spotlight media item id "{uuid}"'])
        return {}

    def api_info(q):
        info = photo_info(con, [q["uuid"]])
        if not info:
            raise LookupError(q["uuid"])
        return info[q["uuid"]]

    api = {"/api/today": lambda q: on_this_day(con, q.get("day")), "/api/stories": lambda q: stories(con), "/api/story": lambda q: story_for_editor(con, q.get("id", "")),
           "/api/sharp": lambda q: {u: fetcher.status(u) for u in q.get("uuids", "").split(",") if u},
           "/api/story_photos": lambda q: story_candidates(con, q.get("id", ""), q.get("q"), q.get("like")),
           "/api/search": api_search, "/api/open": api_open, "/api/info": api_info, "/api/parse": api_parse,
           "/api/galaxy": lambda q: galaxy(con), "/api/overview": lambda q: overview(con),
           "/api/rediscover": lambda q: rediscover(con, min(60, int(q.get("n", 24)))),
           "/api/world": lambda q: world(con), "/api/people": lambda q: people(con),
           "/api/albums": lambda q: albums(con), "/api/album": lambda q: album_view(con, q.get("id", "")),
           "/api/dupes": lambda q: dupes(con, q.get("level", "same") if q.get("level") in DUP_LEVELS else "same",
                                         int(q.get("offset", 0)), min(60, int(q.get("limit", 24)))),
           "/api/person": lambda q: person(con, q.get("name", "")), "/api/days": lambda q: days(con, int(q.get("year", date.today().year))),
           "/api/near": lambda q: near(con, float(q["lat"]), float(q["lon"]), min(500.0, float(q.get("km", 2))), min(120, int(q.get("k", 60)))),
           "/api/timeline": lambda q: timeline(con, q.get("q", ""), int(q.get("per", 1)), q.get("person")),
           "/api/game": lambda q: game_round(con, q.get("mode", "year")),
           "/api/clutter": lambda q: clutter(con, q.get("kind"), int(q.get("offset", 0)), min(200, int(q.get("limit", 60)))),
           "/api/undated": lambda q: next_group(con, (q.get("skip") or "").split("|")),
           "/api/frames": lambda q: frame_list(con, q.get("uuid", "")),
           "/api/recreate": lambda q: recreate_ideas(con, int(q.get("offset", 0)), min(60, int(q.get("limit", 24)))) if q.get("view") == "ideas" else recreations(con),
           "/api/why": lambda q: explain(con, q.get("q", ""), q.get("uuid", "")),
           "/api/picks": lambda q: picks(con, q.get("who")), "/api/loved": lambda q: loved_by(con, q.get("uuid", "")),
           "/api/thennow": lambda q: then_and_now(con, q.get("by") == "person"),
           "/api/math": lambda q: photo_math(con, q["base"], q.get("plus", ""), q.get("minus", ""),
                                             float(q.get("w", 1)), int(q.get("k", 24)))}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x): pass

        def send(self, body, ctype, code=200):
            self.send_response(code); self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def local(self):
            return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

        def gate(self, page):
            """True when this request may go on. Every request must name this server (Host), which stops DNS
            rebinding: a website whose name resolves to 127.0.0.1 can't read photos through the visitor's browser.
            This Mac may use everything; other devices (--lan only) need a signed-in session."""
            if (self.headers.get("host") or "").lower() not in allowed:
                return self.send(b"forbidden", "text/plain", 403)
            if self.local() or (lan and lan.signed_in(self.headers.get("cookie"))):
                return True
            if page:
                return self.send(LOGIN.encode(), "text/html; charset=utf-8")
            return self.send(json.dumps(dict(error="sign in first")).encode(), "application/json", 401)

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items() if v[0]}
            if u.path in ("/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/favicon.ico"):
                if (self.headers.get("host") or "").lower() not in allowed:  # nothing private here, so no sign-in
                    return self.send(b"forbidden", "text/plain", 403)
                if u.path == "/manifest.webmanifest":
                    return self.send(MANIFEST.encode(), "application/manifest+json")
                return self.send(app_icon(512 if "512" in u.path else 180 if "apple" in u.path else 192), "image/png")
            if u.path == "/login":
                return self.send(LOGIN.encode(), "text/html; charset=utf-8") if (self.headers.get("host") or "").lower() in allowed \
                    else self.send(b"forbidden", "text/plain", 403)
            if not self.gate(page=not u.path.startswith(("/api/", "/thumb/", "/photo/", "/frame/"))):
                return
            if u.path == "/api/open" and (demo or not self.local()):
                return self.send(json.dumps(dict(error="Open in Photos only works on the Mac")).encode(), "application/json", 403)
            if u.path == "/":
                # re-read, so edits show on reload; tell the page whether it's on this Mac, and (only then) how phones get in
                server = dict(local=self.local(), lan=lan and self.local() and dict(url=lan.url, code=lan.st["passcode"]),
                              demo=bool(demo))
                page = (WEB / "index.html").read_text().replace("/*SERVER*/{}", json.dumps(server).replace("</", "<\\/"), 1)
                return self.send(page.encode(), "text/html; charset=utf-8")
            if u.path in STATIC:
                return self.send((WEB / u.path.lstrip("/")).read_bytes(), STATIC[u.path])
            name = Path(u.path).name
            try:
                if u.path.startswith("/thumb/"):
                    f = THUMBS / name
                    return self.send(f.read_bytes(), "image/jpeg") if f.exists() else self.send(b"", "text/plain", 404)
                if u.path.startswith("/frame/"):  # /frame/UUID/SECONDS.jpg: a video's moment
                    parts = u.path.split("/")
                    f = FRAMES / parts[2] / parts[3] if len(parts) == 4 and VIDEO_FRAME.fullmatch(parts[2] + "/" + parts[3]) else None
                    return self.send(f.read_bytes(), "image/jpeg") if f and f.exists() else self.send(b"", "text/plain", 404)
                if u.path.startswith("/photo/"):
                    return self.send(photo_jpeg(con, name.removesuffix(".jpg")), "image/jpeg")
                if u.path.startswith("/review/") and STORY_ID.fullmatch(name):
                    r = load_review(con, name, make=True)
                    if "download" in q:  # the file goes to family: wait for full-size copies (~1 s per missing one)
                        photos_app.fetch_in_subprocess(con, story_uuids(r))
                    else:  # the player shows ~5 s per photo, so queued copies arrive ahead of their slides
                        fetcher.add(story_uuids(r))
                    page = render_review(con, r, embed="download" in q).encode()
                    if "download" in q:  # one self-contained file to send to family
                        self.send_response(200); self.send_header("content-type", "text/html; charset=utf-8")
                        self.send_header("content-disposition", f'attachment; filename="{export_name(r)}"')
                        self.send_header("content-length", str(len(page))); self.end_headers()
                        return self.wfile.write(page)
                    return self.send(page, "text/html; charset=utf-8")
                if u.path in api:
                    t = time.time(); res = api[u.path](q)
                    total = con.execute("select count(*) from photos").fetchone()[0]
                    extra = dict(checked=res.checked) if isinstance(res, Checked) else {}
                    return self.send(json.dumps(dict(results=res, ms=int((time.time()-t)*1000), total=total, **extra)).encode(),
                                     "application/json")
            except LookupError as ex:
                return self.send(json.dumps(dict(error=str(ex))).encode(), "application/json", 404)
            self.send(b"not found", "text/plain", 404)

        def do_POST(self):  # the requests that write: signing in, saving an edited story, fetching full-size copies
            # Read the body before any answer, refusals too: closing a connection with a body still unread resets it,
            # and the browser then sees a network error instead of the reason.
            try:
                n = int(self.headers.get("content-length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= 1 << 20:
                self.close_connection = True
                return self.send(b"too large", "text/plain", 413)
            raw = self.rfile.read(n)
            # Only this page may write. Other sites can't send JSON here without a CORS preflight, which we never
            # answer; checking Host too stops DNS rebinding (a site whose name resolves to 127.0.0.1).
            origin = self.headers.get("origin")
            if ((self.headers.get("host") or "").lower() not in allowed or (origin and urlparse(origin).netloc.lower() not in allowed)
                    or self.headers.get("content-type", "").split(";")[0].strip() != "application/json"):
                return self.send(b"forbidden", "text/plain", 403)
            path = urlparse(self.path).path
            if path == "/login" and lan:
                try:
                    body = json.loads(raw[:4096])
                    token = lan.sign_in(self.client_address[0], body.get("code", ""))
                except (PermissionError, ValueError, AttributeError) as ex:
                    return self.send(json.dumps(dict(error=str(ex) or "that's not it")).encode(), "application/json", 403)
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("set-cookie", f"ps_session={token}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("content-length", "2"); self.end_headers(); return self.wfile.write(b"{}")
            if not self.gate(page=False):
                return
            writes = {"/api/album": lambda b: save_album(con, b), "/api/album_preview": lambda b: album_preview(con, b), "/api/album_delete": lambda b: delete_album(str(b.get("id", ""))),
                      "/api/album_photos": lambda b: album_to_photos(con, str(b.get("id", ""))),
                      "/api/dupes": lambda b: dupes_choose(con, b),
                      "/api/dupes_send": lambda b: dupes_send(con, b.get("level") if b.get("level") in DUP_LEVELS else "same"),
                      "/api/recreate": lambda b: recreate_post(con, b),
                      # family picks: from phones too, that's the point
                      "/api/pick": lambda b: pick(con, str(b.get("uuid", "")), b.get("who"), bool(b.get("on", True))),
                      "/api/clutter": lambda b: clutter_choose(con, b), "/api/clutter_send": lambda b: clutter_send(con, str(b.get("kind", ""))),
                      # dates go in this index, not Photos; still only from this Mac, so a guest's guess doesn't stick
                      "/api/undated": lambda b: set_date(con, [str(u) for u in b["uuids"]][:2000], b["year"], b.get("month")),
                      "/api/undated_undo": lambda b: undo_dates(con, [str(u) for u in b["uuids"]][:2000])}
            if path in writes:
                if path in ("/api/album_photos", "/api/dupes_send", "/api/clutter_send") and not self.local():
                    return self.send(json.dumps(dict(error="copying into Photos only works on the Mac")).encode(), "application/json", 403)
                if path in ("/api/undated", "/api/undated_undo") and not self.local():
                    return self.send(json.dumps(dict(error="dates can only be set on the Mac")).encode(), "application/json", 403)
                try:
                    body = json.loads(raw)
                    res = writes[path](body if isinstance(body, dict) else {})
                except (ValueError, LookupError, AttributeError, TypeError) as ex:
                    return self.send(json.dumps(dict(error=str(ex))).encode(), "application/json", 400)
                return self.send(json.dumps(dict(results=res)).encode(), "application/json")
            if path not in ("/api/story", "/api/sharp"):
                return self.send(b"not found", "text/plain", 404)
            try:
                body = json.loads(raw)
                if path == "/api/sharp":  # fetch full-size copies of these photos from iCloud, in the background
                    uuids = [str(u)[:64] for u in body.get("uuids", [])][:200]
                    fetcher.add(uuids)
                    return self.send(json.dumps(dict(results={u: fetcher.status(u) for u in uuids})).encode(), "application/json")
                res = edit_review(con, body)
                fetcher.add(story_uuids(load_review(con, body["id"])))
            except (ValueError, LookupError, AttributeError, TypeError) as ex:
                return self.send(json.dumps(dict(error=str(ex))).encode(), "application/json", 400)
            self.send(json.dumps(dict(results=res)).encode(), "application/json")

    print(f"http://localhost:{a.port}" + (f"  (presenter mode: {demo})" if demo else ""), flush=True)
    if lan:
        print(f"Phones and tablets on this Wi-Fi: {lan.url}  passcode: {lan.st['passcode']}\n"
              f"(or scan the QR code under 📱 on this Mac's page; macOS may ask to allow incoming connections: allow it)", flush=True)
    class Server(ThreadingHTTPServer):
        # A page asks for its scripts and dozens of thumbnails at once. With the default queue of 5 waiting
        # connections, the rest were reset: a photo or a whole script would go missing.
        request_queue_size = 128
        daemon_threads = True
    return Server(("0.0.0.0" if lan else "127.0.0.1", a.port), H)
