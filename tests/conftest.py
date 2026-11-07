import json, sys, threading, pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer

import pyrage, pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


class Fake(BaseHTTPRequestHandler):
    """Tiny stand-in target. It holds no relic behavior: tests in this public repo must not leak quirks."""
    routes = {}

    def _go(self):
        status, body = self.routes.get(self.path, (404, {"error": "nope"}))
        raw = json.dumps(body).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    do_GET = do_POST = _go

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_url():
    Fake.routes = {}
    s = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}", Fake
    s.shutdown()


@pytest.fixture
def sealed_set(tmp_path):
    ident = pyrage.x25519.Identity.generate()
    rows = [{"id": f"HO-{i}", "request": {"method": "GET", "path": f"/{i}"},
             "expected_response": {"status": 200, "headers": {"content-type": "application/json"}, "body": {"n": i}}}
            for i in range(4)]
    p = tmp_path / "set.age"
    p.write_bytes(pyrage.encrypt("\n".join(json.dumps(r) for r in rows).encode(), [ident.to_public()]))
    return p, str(ident)
