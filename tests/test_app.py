import http.client
import json
import threading
import time

import pytest

from app import make_server


@pytest.fixture
def srv(tmp_path):
    out, web = tmp_path / "out", tmp_path / "web"
    (out / "acme.com").mkdir(parents=True)
    (out / "acme.com" / "trace.json").write_text(json.dumps({"domain": "acme.com", "status": "sent", "seconds": 5, "profile": {"name": "Acme"}}))
    (web / "vendor").mkdir(parents=True)
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / "vendor" / "lib.js").write_text("var a=1")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    ran = []
    s = make_server(0, out, web, runner=lambda ds, job, o: (ran.append(ds), job.update(state="done")))
    s.ran = ran
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


def call(s, method, path, body=None, host=None, ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", s.server_port)
    h = {"Host": host or "127.0.0.1:%d" % s.server_port}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        if ctype:
            h["Content-Type"] = ctype
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    return r.status, raw, dict(r.getheaders())


def test_binds_loopback_only(srv):
    assert srv.server_address[0] == "127.0.0.1"


def test_host_header_checked_against_dns_rebinding(srv):
    assert call(srv, "GET", "/api/accounts", host="evil.example.com")[0] == 403
    assert call(srv, "GET", "/api/accounts", host="evil.example.com:%d" % srv.server_port)[0] == 403
    assert call(srv, "GET", "/api/accounts", host="localhost:%d" % srv.server_port)[0] == 200


def test_post_requires_json_content_type(srv):
    assert call(srv, "POST", "/api/run", b'{"domains":["a.com"]}', ctype="text/plain")[0] == 415
    assert call(srv, "POST", "/api/run", b'{"domains":["a.com"]}', ctype="application/x-www-form-urlencoded")[0] == 415
    assert call(srv, "POST", "/api/run", b'{"domains":["a.com"]}', ctype=None)[0] == 415
    assert call(srv, "POST", "/api/run", b"not json")[0] == 400


def test_run_validates_domains_and_starts_job(srv):
    assert call(srv, "POST", "/api/run", {"domains": ["../etc/passwd"]})[0] == 400
    assert call(srv, "POST", "/api/run", {"domains": []})[0] == 400
    assert call(srv, "POST", "/api/run", {"domains": "a.com"})[0] == 400
    st, raw, _ = call(srv, "POST", "/api/run", {"domains": ["https://www.Newco.io/x"]})
    assert st == 202
    time.sleep(0.2)
    assert srv.ran == [["newco.io"]]
    assert json.loads(call(srv, "GET", "/api/job")[1])["state"] == "done"


def test_path_traversal_blocked(srv):
    for p in ["/../secret.txt", "/%2e%2e/secret.txt", "/vendor/../../secret.txt", "/..%2fsecret.txt", "/api/account/..%2f..%2fsecret", "/api/account/../x"]:
        st, raw, _ = call(srv, "GET", p)
        assert st in (400, 404) and b"TOP SECRET" not in raw, p


def test_static_and_vendor_served_with_security_headers(srv):
    st, raw, h = call(srv, "GET", "/")
    assert st == 200 and b"<h1>" in raw
    assert "default-src 'self'" in h["Content-Security-Policy"] and h["X-Content-Type-Options"] == "nosniff"
    st, raw, h = call(srv, "GET", "/vendor/lib.js")
    assert st == 200 and "javascript" in h["Content-Type"]
    assert call(srv, "GET", "/vendor/nope.js")[0] == 404


def test_account_endpoints_and_bad_domains(srv):
    assert json.loads(call(srv, "GET", "/api/account/acme.com")[1])["domain"] == "acme.com"
    assert call(srv, "GET", "/api/account/nope.com")[0] == 404
    assert call(srv, "GET", "/api/account/bad%20domain")[0] == 400
    rows = json.loads(call(srv, "GET", "/api/accounts")[1])
    assert rows[0]["domain"] == "acme.com" and rows[0]["stage"] == "sent"


def test_review_round_trip(srv):
    body = {"stage": "replied", "lead_agrees": "yes", "edit_level": "light", "replied": "yes", "notes": "Asked for pricing"}
    st, raw, _ = call(srv, "POST", "/api/account/acme.com/review", body)
    assert st == 200
    acct = json.loads(call(srv, "GET", "/api/account/acme.com")[1])
    assert acct["human"]["notes"] == "Asked for pricing" and acct["human"]["stage"] == "replied"
    row = json.loads(call(srv, "GET", "/api/accounts")[1])[0]
    assert row["human"]["lead_agrees"] == "yes" and row["stage"] == "replied"


def test_review_rejects_bad_values_and_unknown_accounts(srv):
    assert call(srv, "POST", "/api/account/acme.com/review", {"stage": "hacked"})[0] == 400
    assert call(srv, "POST", "/api/account/acme.com/review", {"evil": "x"})[0] == 400
    assert call(srv, "POST", "/api/account/acme.com/review", {"notes": "x" * 3000})[0] == 400
    assert call(srv, "POST", "/api/account/ghost.com/review", {"stage": "replied"})[0] == 404
    assert call(srv, "POST", "/api/account/bad..com/review", {"stage": "replied"})[0] == 400


def test_other_methods_refused(srv):
    assert call(srv, "PUT", "/api/run", {"a": 1})[0] == 405
    assert call(srv, "DELETE", "/api/account/acme.com", None)[0] == 405
