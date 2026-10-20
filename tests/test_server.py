"""The web server on this Mac: every view's API answers, and only this page can read or write."""
import json, re, socket

import pytest

from photosearch import albums, config, dupes
from server import Server


@pytest.fixture(scope="module")
def srv():
    with pytest.MonkeyPatch.context() as mp:
        s = Server(mp)
        yield s
        s.close()


def test_page_is_served_with_what_it_needs_to_know(srv):
    status, h, body = srv.get("/")
    assert status == 200 and h["content-type"].startswith("text/html")
    server = json.loads(body.decode().split("const SERVER = ", 1)[1].split(";</script>", 1)[0])
    assert server == dict(local=True, lan=None, demo=False)


@pytest.mark.parametrize("path", [
    "/api/search?q=beach", "/api/search?person=Sam", "/api/search?like={beach0}", "/api/today?day=03-12", "/api/stories",
    "/api/story?id=trip-2025-03-10", "/api/story_photos?id=2024", "/api/overview", "/api/rediscover", "/api/world", "/api/people",
    "/api/person?name=Sam", "/api/days?year=2025", "/api/near?lat=38.72&lon=-9.14", "/api/timeline?q=cake",
    "/api/game?mode=place", "/api/math?base=dog&plus=snow", "/api/albums", "/api/dupes", "/api/dupes?level=similar",
    "/api/info?uuid={beach0}", "/api/parse?q=beach", "/api/sharp?uuids={beach0}",
    "/api/picks", "/api/picks?who=Sam", "/api/loved?uuid={beach0}", "/api/search?q=beach&check=1",
])
def test_every_api_answers(srv, lib, path):
    status, h, body = srv.get(path.format(**lib))
    assert status == 200, body[:300]
    assert "results" in json.loads(body) and h["content-type"] == "application/json"


def test_galaxy(srv):
    g = srv.json("/api/galaxy", timeout=300)  # UMAP compiles itself on its first run in a new environment: ~30 s
    assert len(g["uuids"]) == len(g["x"]) == 73 and all(0 <= x <= 1 for x in g["x"])


def test_images(srv, lib):
    status, h, body = srv.get(f"/thumb/{lib['beach0']}.jpg")
    assert status == 200 and body[:2] == b"\xff\xd8"
    status, _, body = srv.get(f"/photo/{lib['beach0']}.jpg")
    assert status == 200 and body[:2] == b"\xff\xd8"


@pytest.mark.parametrize("path", ["/thumb/../index.sqlite", "/thumb/..%2Findex.sqlite", "/thumb/%2e%2e/index.sqlite",
                                  "/review/../albums", "/review/..%2F..%2Fps.py"])
def test_paths_cant_escape(srv, path):
    status, _, body = srv.get(path)
    assert status == 404 and b"SQLite" not in body and b"import" not in body


def test_unknowns_are_404(srv):
    assert srv.get("/api/person?name=Nobody")[0] == 404
    assert srv.get("/api/info?uuid=nope")[0] == 404
    assert srv.get("/nothing")[0] == 404
    assert srv.get("/photo/nope.jpg")[0] == 404


def test_story_page_and_download(srv):
    status, _, body = srv.get("/review/trip-2025-03-10")
    assert status == 200 and b"Lisbon" in body
    status, h, body = srv.get("/review/trip-2025-03-10?download=1")
    assert status == 200 and "attachment" in h["content-disposition"] and b"data:image/jpeg;base64," in body


# ---------------------------------------------------------------- who may ask

@pytest.mark.parametrize("host", ["evil.example:8765", "evil.example", "localhost", "192.168.1.5:{port}"])
def test_other_hosts_are_refused(srv, host):
    """DNS rebinding: a website whose name resolves to 127.0.0.1 still sends its own name as Host."""
    host = host.format(port=srv.port)
    for path in ("/", "/api/search?q=beach", "/thumb/x.jpg", "/login", "/manifest.webmanifest"):
        assert srv.get(path, host=host)[0] == 403, path
    assert srv.post("/api/album", dict(name="x", q="beach"), host=host)[0] == 403


def test_no_host_is_refused(srv):
    with socket.create_connection(("127.0.0.1", srv.port)) as s:
        s.sendall(b"GET /api/search?q=beach HTTP/1.0\r\n\r\n")
        assert s.recv(100).split()[1] == b"403"


def test_bodies_must_have_a_sane_length(srv):
    for n in (b"-1", b"abc", str(2 << 20).encode()):
        with socket.create_connection(("127.0.0.1", srv.port), timeout=5) as s:
            s.sendall(b"POST /api/album HTTP/1.1\r\nHost: localhost:%d\r\nContent-Type: application/json\r\n"
                      b"Content-Length: %s\r\n\r\n{}" % (srv.port, n))
            assert s.recv(100).split()[1] == b"413"


def test_127_0_0_1_is_fine(srv):
    assert srv.get("/", host=f"127.0.0.1:{srv.port}")[0] == 200


def test_writes_need_json(srv):
    """A form on another site can post text/plain without asking first; JSON needs a preflight we never answer."""
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
        status, _, _ = srv.post("/api/album", '{"name":"x","q":"beach"}', headers={"Content-Type": ctype})
        assert status == 403
    assert not (albums.ALBUMS).exists()


def test_writes_from_other_origins_are_refused(srv):
    for origin in ("https://evil.example", "http://localhost:1", "null"):
        assert srv.post("/api/album", dict(name="x", q="beach"), headers={"Origin": origin})[0] == 403
    assert not albums.ALBUMS.exists()
    assert srv.post("/api/album", dict(name="x", q="beach"), headers={"Origin": f"http://localhost:{srv.port}"})[0] == 200


def test_album_round_trip(srv, photos_app):
    a = srv.json("/api/album", dict(name="Dog", q="dog", n=4))
    assert a == dict(id="dog", n=4)
    assert len(srv.json("/api/album?id=dog")["photos"]) == 4
    assert srv.json("/api/album_photos", dict(id="dog")) == dict(added=4, total=4)
    assert srv.json("/api/album_delete", dict(id="dog")) == {}
    assert srv.json("/api/albums") == []


@pytest.mark.parametrize("body", [dict(name=""), dict(name="x"), [1, 2], "null", b"{not json", dict(id="../x", name="x", q="y")])
def test_bad_writes_are_400s(srv, body):
    status, _, data = srv.post("/api/album", body)
    assert status in (400, 404) and "error" in json.loads(data)


def test_dupes_round_trip(srv, lib, photos_app):
    page = srv.json("/api/dupes")
    key = page["groups"][0]["key"]
    srv.json("/api/dupes", dict(key=key, action="nope"))
    assert srv.json("/api/dupes")["total"] == page["total"] - 1
    assert srv.json("/api/dupes_send", dict(level="same"))["album"] == dupes.MAYBE_DELETE
    assert photos_app.added and photos_app.added[0][0] == dupes.MAYBE_DELETE


def test_editing_a_story(srv, lib):
    story = srv.json("/api/story?id=2024")
    first = story["chapters"][0]
    body = dict(id="2024", title="Our year", chapters=[dict(title="One", photos=[dict(uuid=first["photos"][0]["uuid"], caption="hi")])])
    assert srv.json("/api/story", body)["made_by"] == "you"
    assert srv.json("/api/story?id=2024")["title"] == "Our year"
    status, _, _ = srv.post("/api/story", dict(id="2024", chapters=[dict(photos=[dict(uuid="NOT-A-PHOTO")])]))
    assert status == 400
    assert srv.post("/api/story", dict(id="../../x"))[0] in (400, 404)


def test_icons_and_manifest(srv):
    status, h, body = srv.get("/manifest.webmanifest")
    assert status == 200 and json.loads(body)["display"] == "standalone"
    for path in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
        status, h, body = srv.get(path)
        assert status == 200 and body[:4] == b"\x89PNG"


def test_the_pages_own_files(srv):
    for path in ["/app.css"] + [f"/js/{f.name}" for f in (config.WEB / "js").glob("*.js")]:
        status, h, body = srv.get(path)
        assert status == 200 and body and h["content-type"].startswith(("text/css", "text/javascript")), path


@pytest.mark.parametrize("path", ["/index.html", "/review.html", "/js/../index.html", "/js/x.js", "/web/app.css", "/js/", "/config.py"])
def test_nothing_else_is_served(srv, path):
    assert srv.get(path)[0] == 404


def test_the_page_loads_every_script_once():
    page = (config.WEB / "index.html").read_text()
    scripts = re.findall(r'<script src="/js/([\w-]+\.js)"></script>', page)
    assert sorted(scripts) == sorted(f.name for f in (config.WEB / "js").glob("*.js")) and len(set(scripts)) == len(scripts)


def test_many_requests_at_once(srv, lib):
    """A page loads its scripts and a grid of thumbnails in parallel; none may be turned away."""
    import concurrent.futures, http.client

    def get(i):
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
            c.request("GET", f"/thumb/{lib['beach0']}.jpg" if i % 2 else "/js/core.js", headers={"Host": f"localhost:{srv.port}"})
            r = c.getresponse(); r.read(); c.close()
            return r.status
        except OSError as ex:
            return type(ex).__name__
    with concurrent.futures.ThreadPoolExecutor(100) as ex:
        assert set(ex.map(get, range(100))) == {200}


def test_galaxy_forgets_deleted_photos(srv, lib, con):
    assert lib["beach0"] in srv.json("/api/galaxy", timeout=300)["uuids"]
    con.execute("delete from photos where uuid=?", (lib["beach0"],)); con.commit()
    assert lib["beach0"] not in srv.json("/api/galaxy", timeout=300)["uuids"]


def test_a_test_is_judged_from_the_page(srv, lib, tmp_path):
    from photosearch import evals
    q = tmp_path / "q.txt"; q.write_text("a beach at sunset\nsnow\n")
    evals.run("page", "dims=64", n=500, k=3, queries=str(q))
    assert srv.json("/api/evals")[0] == dict(name="page", searches=2, k=3, judges={})
    s = srv.json("/api/eval_sheet?name=page&who=Sam")
    assert s["n"] == 1 and len(s["x"]) == 3 and "date" in s["x"][0] and not {"A", "B"} & set(s)
    assert srv.json("/api/eval_score", dict(name="page", n=1, who="Sam", x=[1], y=[2, 3], first="y")) == dict(left=1)
    status, _, body = srv.post("/api/eval_score", dict(name="page", n=1, who="Sam", x=[9], y=[], first="y"))
    assert status == 400 and b"photo numbers" in body
    status, _, body = srv.get("/api/eval_results?name=page&who=Sam")
    assert status == 404 and b"judge every sheet" in body
    srv.json("/api/eval_score", dict(name="page", n=2, who="Sam", x=[], y=[], first="same"))
    assert srv.json("/api/eval_results?name=page&who=Sam")["judges"]["Sam"]["sheets"] == 2
    status, _, _ = srv.get("/api/eval_sheet?name=../page")
    assert status == 404


def test_claude_judges_through_mcp(lib, tmp_path):
    from photosearch import evals, mcp_server
    q = tmp_path / "q.txt"; q.write_text("a beach at sunset\n")
    evals.run("mcp", "dims=64", n=500, k=3, queries=str(q))
    image, key = mcp_server.eval_sheet("mcp")
    assert json.loads(key)["search"] == "a beach at sunset" and image.data[:2] == b"\xff\xd8"
    assert mcp_server.score_eval_sheet("mcp", 1, [1, 2], [], "x") == "saved; every sheet is judged"
    assert json.loads(mcp_server.eval_sheet("mcp")[0])["done"]
    assert json.loads(mcp_server.eval_sheet()[0])[0]["judges"] == {"claude": 1}


def test_portraits_from_the_page(srv, lib, con):
    import json as j
    pick = lib["cake0"]
    assert srv.json("/api/portrait", dict(name="Sam", uuid=pick)) == dict(name="Sam", cover=pick)
    assert next(p["cover"] for p in srv.json("/api/people") if p["name"] == "Sam") == pick
    status, _, body = srv.post("/api/portrait", dict(name="Sam", uuid=lib["dog0"]))
    assert status == 400 and b"isn't tagged" in body
    status, h, body = srv.get(f"/face/{pick}.jpg?who=Sam")  # no face position yet: the whole thumbnail
    assert status == 200 and h["content-type"] == "image/jpeg" and body == (config.THUMBS / f"{pick}.jpg").read_bytes()
    con.execute("update photos set faces=? where uuid=?", (j.dumps({"Sam": [0.5, 0.4, 0.1]}), pick)); con.commit()
    status, _, crop = srv.get(f"/face/{pick}.jpg?who=Sam")
    assert status == 200 and crop != body and crop[:2] == b"\xff\xd8"
    for bad in ("/face/../index.sqlite", "/face/NOPE.jpg?who=Sam"):
        assert srv.get(bad)[0] == 404
