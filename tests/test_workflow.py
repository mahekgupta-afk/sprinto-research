import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
import respx

from conftest import FakeLLM, html
from outbound import approval, feedback
from outbound.approval import ApprovalError
from outbound.db import connect
from outbound.discover import discover, gate, load_cfg, parse_feed, parse_headline, rank
from outbound.pipeline import process, write_trace
from outbound.resolve import resolve
from test_contacts_validate import GOOD, PROOF
from test_pipeline_send import GOOD_DRAFT, deps_for, handlers, mock_world

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
CFG = load_cfg()


def rss(*items):
    body = "".join("<item><title>%s</title><link>https://n.example/%d</link><pubDate>%s</pubDate></item>" % (t, i, d) for i, (t, d) in enumerate(items))
    return ('<?xml version="1.0"?><rss><channel>%s</channel></rss>' % body).encode()


# ---------- db ----------
def test_db_migrates_and_is_idempotent(tmp_path):
    p = tmp_path / "x.db"
    for _ in range(2):
        with connect(p) as c:
            assert {r["name"] for r in c.execute("select name from sqlite_master where type='table'")} >= {"candidates", "drafts", "learnings"}
            assert c.execute("PRAGMA user_version").fetchone()[0] == 1


# ---------- discovery ----------
def test_parse_headline():
    c = parse_headline("Acme Labs raises $12 million Series A to help clinics - TechCrunch")
    assert c["company"] == "Acme Labs" and c["amount_musd"] == 12 and c["round"] == "series a"
    assert parse_headline("Why startups are raising less") is None
    assert parse_headline("The weather is nice") is None
    assert parse_headline("Foo secures $1.5B Series C")["amount_musd"] == 1500


def test_gates_and_rank():
    ok = parse_headline("Acme raises $12M Series A for SaaS")
    pub = datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert gate(ok, pub, CFG, NOW) is None
    assert gate(parse_headline("Acme raises $12M Series A, acquires Beta"), pub, CFG, NOW).startswith("excluded")
    assert gate(parse_headline("Acme raises $500M Series A"), pub, CFG, NOW) == "amount outside band"
    assert gate(parse_headline("Acme raises $12M Series F"), pub, CFG, NOW) == "round not in scope"
    assert gate(ok, datetime(2026, 1, 1, tzinfo=timezone.utc), CFG, NOW) == "too old or undated"
    assert gate(ok, None, CFG, NOW) == "too old or undated"
    fresh, stale = rank(ok, NOW, CFG, NOW), rank(ok, datetime(2026, 10, 10, tzinfo=timezone.utc), CFG, NOW)
    assert fresh > stale


def test_feed_parser_ignores_entities():
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>'
    items = parse_feed(evil)
    assert "root:" not in json.dumps(items)


PUB = "Mon, 16 Nov 2026 09:00:00 GMT"


@respx.mock
def test_discover_dedupes_resolves_and_applies_cooldown(tmp_path):
    cfg = dict(CFG, queries=["q"])
    respx.get(url__startswith="https://news.google.com/rss/search").respond(200, content=rss(
        ("Acme Labs raises $12M Series A for clinic software - X", PUB), ("Acme Labs raises $12M Series A for clinic software - Y", PUB),
        ("Ghost Co raises $9M seed for payroll tools - X", PUB), ("Boring Co closes $3M seed round, acquires rival", PUB)))
    respx.get("https://acmelabs.com/").respond(200, text=html("Acme Labs builds clinic software for specialist practices. " * 6), headers={"content-type": "text/html"})
    respx.get(url__regex=r"https://(acmelabs|ghostco)\.\w+/__.*").respond(404)
    respx.get(url__regex=r"https://ghostco\.\w+/").respond(404)
    respx.get(url__regex=r"https://acmelabs\.(io|ai|co|app|dev)/").respond(404)
    db = tmp_path / "d.db"
    got = discover(httpx.Client(), db, cfg=cfg, today=NOW)
    names = {c["company"]: c["domain"] for c in got}
    assert names == {"Acme Labs": "acmelabs.com", "Ghost Co": None}  # deduped; acquirer headline dropped; unresolvable is flagged
    assert [c for c in got if c["domain"] is None][0]["note"].startswith("no homepage")
    again = discover(httpx.Client(), db, cfg=cfg, today=NOW)
    assert again == []  # 90 day cooldown


@respx.mock
def test_resolve_needs_name_and_topic_match():
    respx.get(url__regex=r".*/__.*").respond(404)
    respx.get("https://acme.com/").respond(200, text=html("Acme is a gardening shop for roses and tulips. " * 8), headers={"content-type": "text/html"})
    respx.get(url__regex=r"https://acme\.(io|ai|co|app|dev)/").respond(404)
    d, note = resolve(httpx.Client(), "Acme", "Acme raises $9M seed for payroll compliance tooling")
    assert d is None and "topic" in note  # name matches, topic does not: flagged for a human


# ---------- feedback ----------
def test_feedback_capture_retrieve_and_learn(tmp_path):
    db = tmp_path / "f.db"
    assert feedback.capture(db, "a.com", "Old subj", "Line one.\nLine two?", "New subj", "Line one.\nShorter?", 2, "too long") == 2
    assert feedback.capture(db, "b.com", "s", "b", "s", "b") == 0  # nothing changed, nothing learned
    got = feedback.retrieve(db)
    assert any("Shorter?" in g for g in got) and any("too long" in g for g in got)
    llm = FakeLLM({"RulesOut": {"rules": ["Keep the question short.", "  "]}})
    assert feedback.learn(llm, db) == ["Keep the question short."]
    assert feedback.retrieve(db)[0] == "Keep the question short."  # rules come first
    assert feedback.learn(FakeLLM({}), tmp_path / "empty.db") == []


# ---------- approval gate ----------
@respx.mock
def test_pipeline_queues_instead_of_sending_when_approval_required(settings, icp, proofs):
    resend = mock_world()
    st = replace(settings, require_approval=True)
    tr = process("acme.com", deps_for(st, icp, proofs, FakeLLM(handlers(icp, [GOOD_DRAFT]))))
    assert tr["status"] == "pending_approval" and resend.call_count == 0 and "send" not in tr
    assert approval.approval_of(st.db_path, "acme.com")["status"] == "pending"


@respx.mock
def test_learned_preferences_reach_the_draft_prompt(settings, icp, proofs):
    mock_world()
    st = replace(settings, require_approval=True)
    feedback.capture(st.db_path, "z.com", "s", "b", "s", "b", 1, "never open with a compliment")
    llm = FakeLLM(handlers(icp, [GOOD_DRAFT]))
    process("acme.com", deps_for(st, icp, proofs, llm))
    assert any("never open with a compliment" in p for n, p in llm.prompts if n == "DraftOut")


@pytest.fixture
def queued(settings, icp, proofs):
    with respx.mock:
        mock_world()
        st = replace(settings, require_approval=True)
        tr = process("acme.com", deps_for(st, icp, proofs, FakeLLM(handlers(icp, [GOOD_DRAFT]))))
        write_trace(st.out_dir, tr)
    return st


def sender_spy():
    calls = []

    def send(subject, body, intended, *, settings, client):
        calls.append((subject, body, intended, settings.to_email))
        return {"id": "em_9", "to": settings.to_email}
    return send, calls


def test_approve_sends_to_self_updates_everything(queued):
    send, calls = sender_spy()
    out = approval.approve(queued, None, "acme.com", GOOD_DRAFT["subject"], GOOD_DRAFT["body"], 5, "great", sender=send)
    assert out == {"status": "sent", "edited": False} and calls[0][3] == "me@example.com"
    tr = json.loads((queued.out_dir / "acme.com" / "trace.json").read_text())
    assert tr["status"] == "sent" and tr["send"]["id"] == "em_9"
    assert approval.approval_of(queued.db_path, "acme.com")["status"] == "sent"
    with pytest.raises(ApprovalError) as e:  # second approve: nothing waiting
        approval.approve(queued, None, "acme.com", "s", "b", sender=send)
    assert e.value.code == 409 and len(calls) == 1


def test_edited_draft_is_revalidated_and_feedback_captured(queued):
    send, calls = sender_spy()
    bad = GOOD_DRAFT["body"].replace("?", "!")  # breaks the one-question rule
    with pytest.raises(ApprovalError) as e:
        approval.approve(queued, None, "acme.com", GOOD_DRAFT["subject"], bad, sender=send)
    assert any("question mark" in f for f in e.value.failures) and calls == []
    good_edit = GOOD_DRAFT["body"].replace("security questionnaire", "security review")
    out = approval.approve(queued, None, "acme.com", GOOD_DRAFT["subject"], good_edit, 4, "tighter", sender=send)
    assert out["edited"] is True and calls[0][1] == good_edit
    assert any("security review" in t for t in feedback.retrieve(queued.db_path))


def test_reject_records_reason_and_never_sends(queued):
    out = approval.reject(queued, "acme.com", "tone is off", 2)
    assert out == {"status": "rejected"}
    assert json.loads((queued.out_dir / "acme.com" / "trace.json").read_text())["status"] == "rejected"
    assert any("tone is off" in t for t in feedback.retrieve(queued.db_path))
    with pytest.raises(ApprovalError):
        approval.reject(queued, "acme.com")


def test_approval_rejects_bad_domain_and_rating(queued):
    with pytest.raises(ApprovalError) as e:
        approval.approve(queued, None, "../x", "s", "b")
    assert e.value.code == 400
    with pytest.raises(ApprovalError):
        approval.approve(queued, None, "acme.com", "s", "b", rating=9)


# ---------- server endpoints ----------
def test_server_approve_reject_discover(tmp_path):
    import threading, http.client
    from app import make_server
    out, web = tmp_path / "out", tmp_path / "web"
    (out / "a.com").mkdir(parents=True); web.mkdir()
    (out / "a.com" / "trace.json").write_text(json.dumps({"domain": "a.com", "status": "pending_approval"}))
    seen = {}

    def appr(o, d, body):
        seen["approve"] = (d, body)
        if body.get("subject") == "bad":
            raise ApprovalError("nope", ["no markdown"], 400)
        return {"status": "sent"}
    s = make_server(0, out, web, approver=appr, rejecter=lambda o, d, b: {"status": "rejected"}, discoverer=lambda o, n: [{"company": "X", "domain": "x.com"}])
    threading.Thread(target=s.serve_forever, daemon=True).start()

    def post(path, body, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", s.server_port)
        c.request("POST", path, json.dumps(body), {"Host": "127.0.0.1:%d" % s.server_port, "Content-Type": ctype})
        r = c.getresponse()
        return r.status, json.loads(r.read())
    try:
        assert post("/api/account/a.com/approve", {"subject": "s", "body": "b"}) == (200, {"status": "sent"})
        st, j = post("/api/account/a.com/approve", {"subject": "bad", "body": "b"})
        assert st == 400 and j["failures"] == ["no markdown"]
        assert post("/api/account/a.com/reject", {"reason": "r"}) == (200, {"status": "rejected"})
        assert post("/api/account/../x/approve", {})[0] in (400, 404)
        assert post("/api/account/bad..com/approve", {})[0] == 400
        assert post("/api/account/a.com/approve", {}, ctype="text/plain")[0] == 415
        assert post("/api/discover", {"limit": 5})[1]["candidates"][0]["domain"] == "x.com"
        assert post("/api/discover", {"limit": 500})[0] == 400
    finally:
        s.shutdown()


def test_workflows_do_not_inject_inputs_into_shell():
    import re
    from pathlib import Path
    for f in (Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"):
        text = f.read_text()
        for m in re.finditer(r"^\s+run:\s*(.+)$", text, re.M):
            assert "${{" not in m.group(1), (f.name, m.group(1))
        assert "permissions:" in text and "REQUIRE_APPROVAL" in text


def test_next_batch_when_too_few_fit(settings, icp, proofs, monkeypatch):
    from outbound import runner
    batches = [[{"company": "A", "domain": "a.com"}, {"company": "B", "domain": None}], [{"company": "C", "domain": "c.com"}], []]
    monkeypatch.setattr("outbound.discover.discover", lambda *a, **k: batches.pop(0))
    verdicts = {"a.com": "REJECT", "c.com": "QUALIFY"}
    monkeypatch.setattr(runner, "run_batch", lambda ds, d, p=None: [{"domain": x, "verdict_final": verdicts[x]} for x in ds])
    out = runner.run_until_fits(deps_for(settings, icp, proofs, FakeLLM()), min_fits=1)
    assert out == {"rounds": 2, "fits": 1, "researched": 2, "flagged": 1}  # stopped once enough fit; second batch fetched because first had none


def test_flagged_lead_can_be_resolved_by_a_human(tmp_path):
    from outbound.db import connect, now
    from outbound.discover import list_flagged, resolve_flagged
    db = tmp_path / "f.db"
    with connect(db) as c:
        c.execute("INSERT INTO candidates(domain,company,headline,status,flag_reason,found_at) VALUES('?acme','Acme','Acme raises $5M seed','flagged','no homepage matched',?)", (now(),))
    assert list_flagged(db)[0]["key"] == "?acme"
    with pytest.raises(ValueError):
        resolve_flagged(db, "?acme", "../etc")
    assert resolve_flagged(db, "?acme", "https://www.Acme.io/") == "acme.io"
    assert list_flagged(db) == []
    with connect(db) as c:
        assert c.execute("SELECT status FROM candidates WHERE domain='acme.io'").fetchone()[0] == "queued"
    with pytest.raises(LookupError):
        resolve_flagged(db, "?acme", "acme.io")
