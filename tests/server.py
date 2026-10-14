"""Runs `photosearch serve` in this process, so it sees the made-up library and the fake model, and talks to it over HTTP."""
import http.client, http.server, json, socket, threading, time
from argparse import Namespace

from photosearch import server


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


class Server:
    def __init__(self, monkeypatch, lan=False, host="127.0.0.1"):
        self.port, self.host = free_port(), host
        made = []

        class Recorded(http.server.ThreadingHTTPServer):
            def __init__(s, *a, **k):
                super().__init__(*a, **k); made.append(s)
        monkeypatch.setattr(http.server, "ThreadingHTTPServer", Recorded)
        threading.Thread(target=server.cmd_serve, args=(Namespace(port=self.port, lan=lan, new_passcode=False),), daemon=True).start()
        for _ in range(500):
            if made:
                break
            time.sleep(0.02)
        self.httpd = made[0]

    def request(self, method, path, body=None, host=None, headers=None, via=None, timeout=20):
        """(status, headers, body). via: the address to connect to (default this Mac's loopback)."""
        c = http.client.HTTPConnection(via or self.host, self.port, timeout=timeout)
        h = {"Host": host or f"localhost:{self.port}"}
        if body is not None:
            h["Content-Type"] = "application/json"
            body = body if isinstance(body, (bytes, str)) else json.dumps(body)
        h.update(headers or {})
        c.request(method, path, body=body, headers={k: v for k, v in h.items() if v is not None})
        r = c.getresponse()
        out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        c.close()
        return out

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body, **kw):
        return self.request("POST", path, body, **kw)

    def json(self, path, body=None, **kw):
        status, _, data = self.request("GET" if body is None else "POST", path, body, **kw)
        assert status == 200, (status, data[:300])
        return json.loads(data)["results"]

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()
