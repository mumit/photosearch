"""`serve --lan`: phones and tablets on the home Wi-Fi, with a family passcode."""
import hmac, json, os, secrets, socket, threading, time

from .config import DATA

LAN_FILE = DATA / "lan.json"
WORDS = ("maple river otter cedar harbor meadow pebble lantern comet willow ember canyon falcon juniper orchard summit "
         "kettle marble sparrow tulip garnet breeze acorn island").split()

def lan_ip():
    """This Mac's address on the home network (a UDP "connect" sends nothing; it only picks the route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class LanAccess:
    """`serve --lan`: phones and tablets on the home network may use the page after typing the family passcode once;
    each device then keeps a cookie that `serve --lan --new-passcode` revokes. Wrong guesses lock that device out,
    for longer each time."""
    def __init__(self, port, new=False):
        st = {} if new or not LAN_FILE.exists() else json.loads(LAN_FILE.read_text())
        if not st.get("passcode"):
            st = dict(passcode=f"{secrets.choice(WORDS)}-{secrets.choice(WORDS)}-{10 + secrets.randbelow(90)}", sessions=[])
        self.st, self.port, self.ip, self.fails, self.lock = st, port, lan_ip(), {}, threading.Lock()
        self.save()
        name = socket.gethostname().lower().removesuffix(".local")
        self.hosts = {f"{h}:{port}" for h in (self.ip, name, name + ".local")}

    def save(self):
        LAN_FILE.write_text(json.dumps(self.st)); os.chmod(LAN_FILE, 0o600)

    @property
    def url(self):
        return f"http://{self.ip}:{self.port}"

    def signed_in(self, cookies):
        token = next((c.split("=", 1)[1] for c in (cookies or "").split("; ") if c.startswith("ps_session=")), "")
        return bool(token) and any(hmac.compare_digest(token, t) for t in self.st["sessions"])

    def sign_in(self, ip, code):
        """A new session token, or raises PermissionError (wrong code, or locked out after too many)."""
        with self.lock:
            n, until = self.fails.get(ip, (0, 0))
            if time.time() < until:
                raise PermissionError(f"too many tries: wait {int(until - time.time()) + 1} s")
            if not hmac.compare_digest(" ".join(str(code).lower().split()).replace(" ", "-"), self.st["passcode"]):
                n += 1
                self.fails[ip] = (n, time.time() + min(3600, 60 * 2 ** (n - 5)) if n >= 5 else 0)
                raise PermissionError("that's not it")
            self.fails.pop(ip, None)
            token = secrets.token_urlsafe(24)
            self.st["sessions"].append(token); self.save()
            return token


LOGIN = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Photosearch</title><link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#0f0e0c">
<style>body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#0f0e0c;color:#f4efe6;font:16px -apple-system,system-ui,sans-serif}
form{display:flex;flex-direction:column;gap:14px;width:min(340px,calc(100% - 40px));text-align:center}
img{width:84px;height:84px;border-radius:20px;margin:0 auto 6px}h1{font:600 30px ui-serif,"New York",Georgia,serif;margin:0}
p{color:#a39c90;margin:0 0 6px}input{font:inherit;font-size:18px;padding:13px 16px;border-radius:14px;border:1px solid #2f2b27;background:#1d1b18;color:inherit;text-align:center}
button{font:inherit;font-weight:600;padding:13px;border-radius:999px;border:0;background:#f2b33d;color:#1a1408}#err{color:#ff8a7a;min-height:1.3em}</style>
<form id="f"><img src="/icon-192.png" alt=""><h1>Photosearch</h1><p>Type the family passcode. It's shown on the Mac running Photosearch.</p>
<input id="c" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="e.g. maple-river-42" autofocus><button>Open</button><div id="err"></div></form>
<script>
async function go(code) {
  const r = await fetch("/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code }) });
  if (r.ok) return location.replace("/");
  document.getElementById("err").textContent = (await r.json()).error;
}
document.getElementById("f").onsubmit = e => { e.preventDefault(); go(document.getElementById("c").value); };
const code = new URLSearchParams(location.search).get("code");  // the QR code on the Mac carries it
if (code) { history.replaceState(null, "", "/login"); go(code); }
</script>"""
