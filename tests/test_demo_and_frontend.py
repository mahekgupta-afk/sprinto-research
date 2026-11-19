import json
import re
from pathlib import Path

import pytest

import build_demo
from outbound.pipeline import write_trace
from outbound.report import update_review

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def trace(**kw):
    t = {"domain": "acme.com", "status": "sent", "seconds": 5, "profile": {"name": "Acme", "one_liner": "x"},
         "contact": {"person": {"name": "Fay Founder", "title": "CEO", "email": "fay@acme.com", "linkedin": "https://linkedin.com/in/fay", "role": "founder", "source": "hunter"},
                     "order": ["founder"], "note": "n", "fallback": {"x": "fay@acme.com"}},
         "intended": "Fay <fay@acme.com>", "gmail_link": "https://mail.google.com/?to=me%40x.com", "send": {"to": "me@x.com"},
         "error": "boom me@x.com", "evidence": [{"id": "E1", "topic": "t", "claim": "mail sales@acme.com", "quote": "q", "url": "u"}],
         "email": {"drafts": [{"n": 1, "subject": "s", "body": "reach b@x.io", "code_failures": [], "passed": True, "review": None}], "best": None, "rewrites": 0}}
    t.update(kw)
    return t


@pytest.fixture
def built(tmp_path):
    out = tmp_path / "out"
    write_trace(out, trace())
    update_review(out / "review.csv", "acme.com", {"notes": "secret note", "stage": "replied"})
    site = tmp_path / "site"
    build_demo.build(out, WEB, site)
    return site


def test_demo_contains_no_emails_notes_links_or_keys(built):
    assert build_demo.scan(built) == []
    blob = "".join(f.read_text() for f in (built / "data").rglob("*.json"))
    for needle in ["fay@acme.com", "me@x.com", "secret note", "linkedin.com", "mail.google.com", "boom", "sales@acme.com", "b@x.io"]:
        assert needle not in blob, needle
    assert "Fay F." in blob and "[hidden]" in blob


def test_demo_snapshot_files_exist(built):
    assert (built / "index.html").exists() and (built / "data" / "accounts.json").exists()
    assert json.loads((built / "data" / "account" / "acme.com.json").read_text())["domain"] == "acme.com"
    assert not (built / "app.py").exists() and not (built / ".env").exists()


def test_build_refuses_when_key_shaped_string_survives(tmp_path):
    out = tmp_path / "out"
    write_trace(out, trace(evidence=[{"id": "E1", "topic": "t", "claim": "c", "quote": "AIza" + "x" * 30, "url": "u"}]))
    site = tmp_path / "site"
    with pytest.raises(build_demo.BuildRefused):
        build_demo.build(out, WEB, site)
    assert not site.exists()


def test_scan_catches_surviving_email(tmp_path):
    (tmp_path / "a.json").write_text('{"x": "someone@example.com"}')
    assert build_demo.scan(tmp_path)


def test_vercel_config_and_ignore():
    v = json.loads((ROOT / "vercel.json").read_text())
    assert v["outputDirectory"] == "site"
    hdr = {h["key"]: h["value"] for h in v["headers"][0]["headers"]}
    assert "default-src 'self'" in hdr["Content-Security-Policy"] and hdr["X-Content-Type-Options"] == "nosniff" and hdr["Referrer-Policy"] == "no-referrer"
    ign = (ROOT / ".vercelignore").read_text().split()
    assert "!/site" in ign and "!/vercel.json" in ign and "/*" in ign


# ---- frontend safety ----
def js_files():
    return list((WEB / "js").glob("*.js"))


def test_scraped_text_never_goes_through_innerhtml():
    for f in js_files():
        t = f.read_text()
        for bad in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"]:
            assert bad not in t, (f.name, bad)


def test_no_inline_styles_or_external_resources():
    html = (WEB / "index.html").read_text()
    assert " style=" not in html and "<style" not in html and "onclick=" not in html
    for f in [WEB / "index.html", WEB / "styles.css", *js_files()]:
        for url in re.findall(r"https?://[^\s\"')]+", f.read_text()):
            assert url.startswith("http://www.w3.org/2000/svg") or url.startswith("https://") and "linkedin" in url or False, (f.name, url)


def test_demo_mode_is_host_based_and_read_only():
    api = (WEB / "js" / "api.js").read_text()
    assert '"localhost", "127.0.0.1"' in api and "data/accounts.json" in api and "read-only demo" in api
    main = (WEB / "js" / "main.js").read_text()
    assert "Read-only demo" in main and "contact details hidden" in main


def test_reduced_motion_and_focus_styles_present():
    css = (WEB / "styles.css").read_text()
    assert "prefers-reduced-motion: reduce" in css and ":focus-visible" in css
