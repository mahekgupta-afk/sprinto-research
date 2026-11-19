#!/usr/bin/env python
"""Local CRM. stdlib only. Binds 127.0.0.1, checks Host, JSON-only POSTs, no path traversal."""
from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from outbound.accounts import list_accounts
from outbound.config import ROOT, clean_domain, scrub, valid_domain
from outbound.approval import ApprovalError, approval_of, approve, reject
from outbound.report import read_review, update_review

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MAX_BODY = 20_000


class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"state": "idle", "total": 0, "done": 0, "current": "", "error": ""}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **kw):
        with self.lock:
            self.state.update(kw)


def default_runner(domains, job: Job, out_dir: Path):
    from outbound.config import load_settings
    from outbound.runner import build_deps, run_batch
    s = load_settings()
    try:
        deps = build_deps(s)
        job.update(state="running", total=len(domains), done=0)
        run_batch(domains, deps, lambda d, t: job.update(done=job.snapshot()["done"] + 1, current=d))
        job.update(state="done", current="")
    except Exception as e:  # noqa: BLE001
        job.update(state="error", error=scrub(str(e), s), current="")


def default_approver(out_dir: Path, domain: str, body: dict) -> dict:
    from outbound.config import load_settings
    from outbound.scrape import make_client
    s = load_settings()
    s.out_dir = Path(out_dir)
    miss = [k for k in ("RESEND_API_KEY", "TO_EMAIL") if k in s.missing()]
    if miss:
        raise ApprovalError("Missing in .env: " + ", ".join(miss))
    return approve(s, make_client(), domain, str(body.get("subject", "")), str(body.get("body", "")), body.get("rating"), str(body.get("note", "")))


def default_rejecter(out_dir: Path, domain: str, body: dict) -> dict:
    from outbound.config import load_settings
    s = load_settings()
    s.out_dir = Path(out_dir)
    return reject(s, domain, str(body.get("reason", "")), body.get("rating"))


def default_discoverer(out_dir: Path, limit: int) -> list:
    from outbound.discover import discover
    from outbound.scrape import make_client
    return discover(make_client(), Path(out_dir) / "autopilot.db", limit)


def make_server(port: int = 8000, out_dir: Path = None, web_dir: Path = None, runner=default_runner,
                approver=default_approver, rejecter=default_rejecter, discoverer=default_discoverer) -> ThreadingHTTPServer:
    out_dir = Path(out_dir or ROOT / "out")
    web_dir = Path(web_dir or ROOT / "web").resolve()
    job = Job()
    api_re = re.compile(r"^/api/account/([^/]+)(/review|/approve|/reject)?$")

    class H(BaseHTTPRequestHandler):
        server_version = "CRM"
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode())

        def _host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            ok = {"127.0.0.1:%d" % self.server.server_port, "localhost:%d" % self.server.server_port}
            if host not in ok:
                self._json(403, {"error": "bad host"})
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            path = urlparse(self.path).path
            if path == "/api/accounts":
                return self._json(200, list_accounts(out_dir))
            if path == "/api/job":
                return self._json(200, job.snapshot())
            m = api_re.match(path)
            if m and not m.group(2):
                d = clean_domain(m.group(1))
                if not valid_domain(d):
                    return self._json(400, {"error": "bad domain"})
                f = out_dir / d / "trace.json"
                if not f.exists():
                    return self._json(404, {"error": "not found"})
                tr = json.loads(f.read_text())
                tr["human"] = read_review(out_dir / "review.csv").get(d, {})
                ap = approval_of(out_dir / "autopilot.db", d) if (out_dir / "autopilot.db").exists() else None
                tr["approval"] = {k: ap[k] for k in ("status", "rating", "note", "created_at", "decided_at")} if ap else None
                return self._json(200, tr)
            if path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            self._static(path)

        def _static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            if "\x00" in rel or ".." in Path(rel).parts:
                return self._json(404, {"error": "not found"})
            try:
                f = (web_dir / rel).resolve()
                f.relative_to(web_dir)
            except (ValueError, OSError):
                return self._json(404, {"error": "not found"})
            if not f.is_file():
                return self._json(404, {"error": "not found"})
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))

        def _body(self):
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                self._json(415, {"error": "JSON only"})
                return None
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._json(413, {"error": "bad length"})
                return None
            try:
                obj = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._json(400, {"error": "bad json"})
                return None
            if not isinstance(obj, dict):
                self._json(400, {"error": "object expected"})
                return None
            return obj

        def do_POST(self):
            if not self._host_ok():
                return
            path = urlparse(self.path).path
            body = self._body()
            if body is None:
                return
            if path == "/api/run":
                ds = body.get("domains")
                if not isinstance(ds, list) or not ds or len(ds) > 50:
                    return self._json(400, {"error": "domains: 1-50 items"})
                clean = [clean_domain(str(x)) for x in ds]
                bad = [x for x in clean if not valid_domain(x)]
                if bad:
                    return self._json(400, {"error": "invalid domain", "domains": bad})
                if job.snapshot()["state"] == "running":
                    return self._json(409, {"error": "a run is already in progress"})
                job.update(state="running", total=len(clean), done=0, current="", error="")
                threading.Thread(target=runner, args=(clean, job, out_dir), daemon=True).start()
                return self._json(202, {"started": len(clean)})
            if path == "/api/discover":
                lim = body.get("limit", 10)
                if not isinstance(lim, int) or not 1 <= lim <= 25:
                    return self._json(400, {"error": "limit: 1-25"})
                try:
                    return self._json(200, {"candidates": discoverer(out_dir, lim)})
                except Exception as e:  # noqa: BLE001
                    return self._json(502, {"error": scrub(str(e))})
            m = api_re.match(path)
            if m and m.group(2) in ("/approve", "/reject"):
                d = clean_domain(m.group(1))
                if not valid_domain(d):
                    return self._json(400, {"error": "bad domain"})
                try:
                    fn = approver if m.group(2) == "/approve" else rejecter
                    return self._json(200, fn(out_dir, d, body))
                except ApprovalError as e:
                    return self._json(e.code, {"error": str(e), "failures": e.failures})
                except Exception as e:  # noqa: BLE001
                    return self._json(502, {"error": scrub(str(e))})
            if m and m.group(2) == "/review":
                d = clean_domain(m.group(1))
                if not valid_domain(d):
                    return self._json(400, {"error": "bad domain"})
                if not (out_dir / d / "trace.json").exists():
                    return self._json(404, {"error": "unknown account"})
                try:
                    saved = update_review(out_dir / "review.csv", d, body)
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {"saved": saved})
            self._json(404, {"error": "not found"})

        def do_PUT(self):
            self._json(405, {"error": "method not allowed"})
        do_DELETE = do_PATCH = do_PUT

    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = make_server(port)
    print("CRM on http://127.0.0.1:%d" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
