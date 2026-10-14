"""`photosearch demo-check`: before recording or sharing a demo, make sure its index gives away nothing from your own
library. Run with PHOTOSEARCH_DATA pointing at the demo's data folder, and the real one as the argument:

    PHOTOSEARCH_DATA=data-demo photosearch demo-check data

It serves the demo in presenter mode, reads everything the page can show (every view, story, year and place, and
searches for each name in your library), and fails on any name tagged in your library, any place name from near your
home, any of your library's photo ids, or a location near your home. It also has macOS's Vision look for faces and
people in every demo photo, and reports faces Photos itself has found in the demo library. Vision mistakes some
statues, carvings and animals for people: once you've looked, list those in the demo's data folder as
checked-by-eye.json, {"uuid": "why it's fine"}, and they're reported as looked at instead. Likewise a place near home
you're happy to show (a big city nearby, say) can be listed in approved-places.json, {"place": "why"}."""
import http.client, json, re, socket, sqlite3, sys, threading
from argparse import Namespace
from pathlib import Path
from urllib.parse import quote

from .config import DATA
from .places import AWAY_KM, homes, km
from .store import db, index_library


def your_library(real):
    """What must not appear: (names, place names near home, photo ids, home locations) from the real index."""
    con = sqlite3.connect(f"file:{Path(real) / 'index.sqlite'}?mode=ro", uri=True)
    rows = con.execute("select uuid, date, persons, place, lat, lon, geo from photos").fetchall()
    names = set()
    for r in rows:
        for n in json.loads(r[2] or "[]"):
            names |= {n} | {w for w in n.split() if len(w) >= 3}
    home = list(homes([(r[1], r[4], r[5]) for r in rows]).values())
    places, broad = set(), set()
    for u, d, ps, place, la, lo, g in rows:
        geo = json.loads(g or "{}")
        broad |= {geo.get("state"), geo.get("country")}  # "Canada" says little; demo trips may be there too
        if la is not None and home and min(km(h, (la, lo)) for h in home) <= AWAY_KM:
            places |= {p.strip() for p in (place or "").split(",")} | set(geo.values())
    places = {p for p in places - broad if p and len(p) >= 3}
    return names, places, {r[0] for r in rows}, home


def serve(port):
    """The demo, in presenter mode, answering in this process."""
    from .server import make_server
    httpd = make_server(Namespace(port=port, lan=False, new_passcode=False, demo=True))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def crawl(port, names):
    """(path, text) for everything the page can show."""
    def get(path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
        c.request("GET", path, headers={"Host": f"localhost:{port}"})
        r = c.getresponse(); body = r.read(); c.close()
        return r.status, body.decode("utf-8", "replace")

    out = []
    def take(path):
        status, text = get(path)
        out.append((path, text))
        return json.loads(text)["results"] if status == 200 and path.startswith("/api/") else None

    take("/")
    ov = take("/api/overview")
    for p in ("/api/stories", "/api/people", "/api/world", "/api/galaxy", "/api/albums", "/api/rediscover?n=60",
              "/api/dupes?limit=60", "/api/dupes?level=similar&limit=60", "/api/today", "/api/timeline?q=" + quote("a photo")):
        take(p)
    for s in take("/api/stories") or []:
        take(f"/api/story?id={s['id']}"); take(f"/review/{s['id']}")
    for y, _ in ov["years"]:
        take(f"/api/days?year={y}")
    for r in (take("/api/world") or {}).get("regions", []):
        take(f"/api/near?lat={r['lat']}&lon={r['lon']}&km=50&k=120")
    for m in range(1, 13):
        take(f"/api/today?day={m:02}-15")
    for q in ["a person", "people", "a child", "a baby", "a family", "a house", "a street sign", "a document", "a school"]:
        take(f"/api/search?k=120&q={quote(q)}")
    for n in sorted(names):  # your people, by name, as words and as a filter: nothing may come back about them
        take(f"/api/search?k=60&q={quote(n)}"); take(f"/api/search?k=60&person={quote(n)}")
    for _ in range(10):
        take("/api/game?mode=year"); take("/api/game?mode=place")
    return out


def look_for_people():
    """{uuid: (faces, people)} where macOS's Vision finds any in a demo photo; None if Vision isn't available."""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError:
        return None
    found = {}
    for u, src in db().execute("select uuid, src from photos"):
        h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(src), None)
        faces = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        people = Vision.VNDetectHumanRectanglesRequest.alloc().init(); people.setUpperBodyOnly_(False)
        h.performRequests_error_([faces, people], None)
        n = (len(faces.results() or []), len(people.results() or []))
        if any(n):
            found[u] = n
    return found


def cmd_demo_check(a):
    real = Path(a.real).resolve()
    if real == DATA.resolve():
        sys.exit("give your own library's data folder as the argument, and the demo's as PHOTOSEARCH_DATA")
    names, places, ids, home = your_library(real)
    approved = json.loads((DATA / "approved-places.json").read_text()) if (DATA / "approved-places.json").exists() else {}
    places -= set(approved)
    problems = []
    con = db()
    for u, ps, la, lo in con.execute("select uuid, persons, lat, lon from photos"):
        if u in ids:
            problems.append(f"photo {u} is from your own library")
        if json.loads(ps or "[]"):
            problems.append(f"photo {u} has people tagged: {ps}")
        if la is not None and home and min(km(h, (la, lo)) for h in home) <= AWAY_KM:
            problems.append(f"photo {u} has a location near your home")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    httpd = serve(port)
    try:
        pages = crawl(port, names)
    finally:
        httpd.shutdown()
    words = sorted(names | places, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in words) + r")(?![\w-])", re.I) if words else None
    uuid = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", re.I)
    for path, text in pages:
        found = {m.group(1) for m in pattern.finditer(text)} if pattern else set()
        found |= {u for u in uuid.findall(text) if u.upper() in ids}
        for m in sorted(found):
            problems.append(f"{path} shows {m!r}" + (" (a name in your library)" if m in names else ""))
    seen = look_for_people()
    ok = json.loads((DATA / "checked-by-eye.json").read_text()) if (DATA / "checked-by-eye.json").exists() else {}
    for u, (f, p) in (seen or {}).items():
        if u in ok:
            print(f"  (looked at: {u}, {ok[u]})")
        else:
            problems.append(f"photo {u}: Vision sees {f} face(s), {p} person(s)")
    try:
        import osxphotos
        lib = osxphotos.PhotosDB(dbfile=index_library())
        for p in lib.photos(intrash=False):
            if p.face_info or p.persons:
                problems.append(f"photo {p.uuid}: Photos found {len(p.face_info)} face(s) in it")
    except Exception as ex:
        print(f"(couldn't ask Photos about faces: {ex})")
    n = con.execute("select count(*) from photos").fetchone()[0]
    print(f"checked {n} demo photos and {len(pages)} pages and answers, against {len(names)} names, {len(places)} places "
          f"near home and {len(ids)} photo ids from {real}" + ("" if seen is not None else " (Vision not available)"))
    for p in problems:
        print("  ✗", p)
    if problems:
        sys.exit(f"{len(problems)} problem(s): don't record or share this demo yet")
    print("✓ nothing from your own library")
