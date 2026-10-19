"""`serve --lan`: phones and tablets on the home Wi-Fi get in with the family passcode, and only then.

The HTTP tests connect through this Mac's own Wi-Fi address, so the server sees a device that isn't this Mac."""
import json, os, stat, time

import pytest

from photosearch import albums, lan
from server import Server

IP = lan.lan_ip()
needs_wifi = pytest.mark.skipif(IP.startswith("127."), reason="not on a network")


# ---------------------------------------------------------------- the passcode

@pytest.fixture
def access():
    return lan.LanAccess(8765)


def test_passcode_looks_like_words_and_a_number(access):
    a, b, n = access.st["passcode"].split("-")
    assert a in lan.WORDS and b in lan.WORDS and 10 <= int(n) <= 99


def test_passcode_file_is_private(access):
    assert stat.S_IMODE(os.stat(lan.LAN_FILE).st_mode) == 0o600


def test_typing_is_forgiving(access):
    a, b, n = access.st["passcode"].split("-")
    assert access.sign_in("1.2.3.4", f"  {a.title()} {b.upper()}  {n} ")


def test_sessions(access):
    token = access.sign_in("1.2.3.4", access.st["passcode"])
    assert access.signed_in(f"theme=dark; ps_session={token}")
    assert not access.signed_in(f"ps_session={token}x") and not access.signed_in("ps_session=") and not access.signed_in(None)
    assert lan.LanAccess(8765).signed_in(f"ps_session={token}")  # kept across restarts
    assert not lan.LanAccess(8765, new=True).signed_in(f"ps_session={token}")  # --new-passcode signs everyone out


def test_wrong_guesses_lock_that_device_out_for_longer_each_time(access, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    for _ in range(4):
        with pytest.raises(PermissionError, match="not it"):
            access.sign_in("1.2.3.4", "wrong")
    access.sign_in("5.6.7.8", access.st["passcode"])  # four wrong is fine
    with pytest.raises(PermissionError, match="not it"):
        access.sign_in("1.2.3.4", "wrong")
    with pytest.raises(PermissionError, match="too many"):
        access.sign_in("1.2.3.4", access.st["passcode"])  # locked out, even with the right one
    assert access.sign_in("5.6.7.8", access.st["passcode"])  # another device isn't
    now[0] += 61
    with pytest.raises(PermissionError, match="not it"):
        access.sign_in("1.2.3.4", "wrong")  # the sixth: two minutes
    now[0] += 61
    with pytest.raises(PermissionError, match="too many"):
        access.sign_in("1.2.3.4", access.st["passcode"])
    now[0] += 60
    assert access.sign_in("1.2.3.4", access.st["passcode"])
    assert "1.2.3.4" not in access.fails  # and a success forgives


# ---------------------------------------------------------------- over the network

@pytest.fixture(scope="module")
def srv():
    with pytest.MonkeyPatch.context() as mp:
        s = Server(mp, lan=True)
        s.passcode = json.loads(lan.LAN_FILE.read_text())["passcode"]
        yield s
        s.close()


def phone(srv, method, path, body=None, cookie=None, host=None):
    return srv.request(method, path, body, host=host or f"{IP}:{srv.port}", via=IP,
                       headers={"Cookie": cookie} if cookie else None)


@pytest.fixture(scope="module")
def cookie(srv):
    status, h, _ = phone(srv, "POST", "/login", dict(code=srv.passcode))
    assert status == 200
    return h["set-cookie"].split(";")[0]


@needs_wifi
def test_a_new_device_sees_only_the_sign_in_page(srv):
    status, _, body = phone(srv, "GET", "/")
    assert status == 200 and b"family passcode" in body
    assert srv.passcode.encode() not in body and b"const SERVER" not in body
    for path in ("/api/search?q=beach", "/api/people", "/thumb/x.jpg", "/photo/x.jpg"):
        assert phone(srv, "GET", path)[0] == 401, path
    assert phone(srv, "POST", "/api/album", dict(name="x", q="beach"))[0] == 401
    assert not albums.ALBUMS.exists()


@needs_wifi
def test_installing_needs_no_sign_in(srv):
    assert phone(srv, "GET", "/manifest.webmanifest")[0] == 200
    assert phone(srv, "GET", "/apple-touch-icon.png")[0] == 200


@needs_wifi
def test_signing_in_sets_a_strict_cookie(srv):
    status, h, _ = phone(srv, "POST", "/login", dict(code=srv.passcode))
    assert status == 200
    attrs = {a.strip().split("=")[0].lower() for a in h["set-cookie"].split(";")}
    assert {"httponly", "samesite", "max-age", "path"} <= attrs and "SameSite=Strict" in h["set-cookie"]


@needs_wifi
def test_signed_in_devices_can_browse_but_not_see_the_passcode(srv, cookie, lib):
    status, _, body = phone(srv, "GET", "/", cookie=cookie)
    server = json.loads(body.decode().split("const SERVER = ", 1)[1].split(";</script>", 1)[0])
    assert not server["local"] and not server["lan"] and srv.passcode.encode() not in body
    status, _, body = phone(srv, "GET", "/api/search?q=beach", cookie=cookie)
    assert status == 200 and json.loads(body)["results"]
    assert phone(srv, "GET", f"/thumb/{lib['beach0']}.jpg", cookie=cookie)[0] == 200


@needs_wifi
def test_some_things_only_work_on_the_mac(srv, cookie, photos_app):
    assert phone(srv, "GET", "/api/open?uuid=x", cookie=cookie)[0] == 403
    phone(srv, "POST", "/api/album", dict(name="Dog", q="dog", n=3), cookie=cookie)
    assert phone(srv, "POST", "/api/album_photos", dict(id="dog"), cookie=cookie)[0] == 403
    assert phone(srv, "POST", "/api/dupes_send", dict(level="same"), cookie=cookie)[0] == 403
    assert phone(srv, "POST", "/api/undated", dict(uuids=["x"], year=2007), cookie=cookie)[0] == 403
    assert phone(srv, "POST", "/api/clutter_send", dict(kind="papers"), cookie=cookie)[0] == 403
    assert photos_app.added == []


@needs_wifi
def test_phones_can_pick_favourites(srv, cookie, lib):
    status, _, body = phone(srv, "POST", "/api/pick", dict(uuid=lib["dog0"], who="Sam"), cookie=cookie)
    assert status == 200 and json.loads(body)["results"] == ["Sam"]


@needs_wifi
def test_a_made_up_cookie_doesnt_work(srv):
    assert phone(srv, "GET", "/api/people", cookie="ps_session=guess")[0] == 401


@needs_wifi
def test_the_mac_itself_needs_no_passcode_and_is_shown_it(srv):
    status, _, body = srv.get("/")
    server = json.loads(body.decode().split("const SERVER = ", 1)[1].split(";</script>", 1)[0])
    assert server["local"] and server["lan"] == dict(url=f"http://{IP}:{srv.port}", code=srv.passcode)


@needs_wifi
def test_claiming_to_be_localhost_doesnt_help(srv):
    assert phone(srv, "GET", "/api/people", host=f"localhost:{srv.port}")[0] == 401


@needs_wifi
def test_other_names_for_this_mac_are_refused(srv):
    assert phone(srv, "GET", "/", host=f"evil.example:{srv.port}")[0] == 403
    status, _, _ = phone(srv, "POST", "/login", dict(code=srv.passcode), host=f"evil.example:{srv.port}")
    assert status == 403


@needs_wifi
def test_lockout_over_http(monkeypatch):
    s = Server(monkeypatch, lan=True)
    try:
        code = json.loads(lan.LAN_FILE.read_text())["passcode"]
        for _ in range(5):
            assert phone(s, "POST", "/login", dict(code="wrong"))[0] == 403
        status, _, body = phone(s, "POST", "/login", dict(code=code))
        assert status == 403 and "too many" in json.loads(body)["error"]
        status, _, _ = s.post("/login", dict(code=code))  # this Mac isn't locked out
        assert status == 200
    finally:
        s.close()
