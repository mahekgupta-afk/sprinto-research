import inspect
import json

import httpx
import respx

from conftest import FakeLLM, html
from outbound.contacts import Hunter
from outbound.pipeline import Deps, process, write_trace
from outbound.report import load_traces, write_reports, write_review_csv, update_review, read_review
from outbound.runner import run_batch
from outbound.send import send_email
from test_contacts_validate import GOOD, PROOF, SUBJ

HOME = ("Acme builds payroll software for hospitals and clinics. We process payroll for hospitals across 12 states. "
        "Trusted by leading health systems. Talk to sales about our enterprise plan. ") * 3


def picks_all(icp, bucket_for=None):
    out = []
    for s in icp["signals"]:
        best = max(s["buckets"], key=lambda b: b["points"])
        out.append({"signal": s["id"], "bucket": best["id"], "evidence_ids": ["E1"]})
    return out


def handlers(icp, drafts, review=(9, 9, 9)):
    return {
        "ExtractOut": {"facts": [{"topic": "customers", "claim": "serves hospitals in 12 states", "quote": "We process payroll for hospitals across 12 states", "url": "https://acme.com/"}],
                       "profile": {"name": "Acme", "one_liner": "payroll software for hospitals", "product_type": "software", "headcount": 40}},
        "QualifyOut": {"picks": picks_all(icp), "disqualifiers": []},
        "PainsOut": {"pains": [{"pain": "Hospital buyers demand security proof", "evidence_ids": ["E1"], "data_handled": "payroll data", "buyer": "hospital CFOs"}]},
        "DraftOut": drafts,
        "ReviewOut": {"specificity": review[0], "relevance": review[1], "reply_likelihood": review[2], "critique": "ok"},
    }


def deps_for(settings, icp, proofs, llm):
    http = httpx.Client()
    return Deps(settings=settings, llm=llm, http=http, hunter=Hunter(settings, http), icp=icp, proof_lines=proofs)


def mock_world(resend_ok=True):
    respx.get(url__regex=r"https://acme\.com/__probe.*").respond(404)
    respx.get("https://acme.com/").respond(200, text=html(HOME), headers={"content-type": "text/html"})
    respx.get(url__regex=r"https://acme\.com/.+").respond(404)
    respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": [
        {"email": "fay@acme.com", "first_name": "Fay", "last_name": "Founder", "position": "Founder & CEO", "confidence": 90}]}})
    return respx.post("https://api.resend.com/emails").respond(200 if resend_ok else 500, json={"id": "em_1"})


GOOD_DRAFT = {"subject": SUBJ, "body": GOOD.replace("Priya", "Fay"), "hook_evidence_id": "E1", "proof_line": PROOF[0]}


@respx.mock
def test_qualified_company_is_sent_to_self_only(settings, icp, proofs):
    resend = mock_world()
    llm = FakeLLM(handlers(icp, [GOOD_DRAFT]))
    tr = process("acme.com", deps_for(settings, icp, proofs, llm))
    assert tr["status"] == "sent", tr.get("error")
    req = json.loads(resend.calls[0].request.content)
    assert req["to"] == ["me@example.com"]  # never the prospect
    assert "fay@acme.com" not in req["to"]
    assert req["text"].rstrip().endswith("Intended recipient: Fay Founder <fay@acme.com>, Founder & CEO at Acme")
    assert tr["contact"]["person"]["role"] == "founder"  # headcount 40 -> founder first
    assert tr["gmail_link"].startswith("https://mail.google.com/") and "me%40example.com" in tr["gmail_link"]


@respx.mock
def test_nothing_passing_validation_is_held_and_not_sent(settings, icp, proofs):
    resend = mock_world()
    bad = {**GOOD_DRAFT, "body": GOOD_DRAFT["body"] + " Why not now?"}  # two question marks, every time
    llm = FakeLLM(handlers(icp, [bad]))
    tr = process("acme.com", deps_for(settings, icp, proofs, llm))
    assert tr["status"] == "held" and resend.call_count == 0
    assert len(tr["email"]["drafts"]) == 4 and tr["email"]["best"] is None


@respx.mock
def test_low_reviewer_score_triggers_rewrite_then_keeps_best_passing(settings, icp, proofs):
    resend = mock_world()
    h = handlers(icp, [GOOD_DRAFT])
    scores = [(5, 6, 5), (8, 9, 8)]
    llm = FakeLLM(h)
    seq = iter(scores)
    h["ReviewOut"] = lambda prompt: dict(zip(["specificity", "relevance", "reply_likelihood"], next(seq)), critique="be sharper")
    tr = process("acme.com", deps_for(settings, icp, proofs, llm))
    assert tr["status"] == "sent" and tr["email"]["rewrites"] == 1
    assert tr["email"]["best"]["n"] == 2 and tr["email"]["reviewer_ok"]
    # the critique went into the rewrite prompt
    assert any("be sharper" in p for n, p in llm.prompts if n == "DraftOut")


@respx.mock
def test_not_qualified_never_touches_hunter_or_resend(settings, icp, proofs):
    resend = mock_world()
    h = handlers(icp, [GOOD_DRAFT])
    h["ExtractOut"]["profile"]["headcount"] = 9000
    tr = process("acme.com", deps_for(settings, icp, proofs, FakeLLM(h)))
    assert tr["status"] == "not_qualified" and tr["verdict_final"] == "DISQUALIFIED"
    assert resend.call_count == 0 and "contact" not in tr


@respx.mock
def test_no_contact_status(settings, icp, proofs):
    mock_world()
    respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": []}})
    h = handlers(icp, [GOOD_DRAFT])
    h["PeopleOut"] = {"names": [], "titles": []}
    tr = process("acme.com", deps_for(settings, icp, proofs, FakeLLM(h, search_text="nothing")))
    assert tr["status"] == "no_contact"


def test_send_email_has_no_recipient_parameter():
    params = set(inspect.signature(send_email).parameters)
    assert not params & {"to", "to_email", "recipient", "email", "cc", "bcc", "address"}


@respx.mock
def test_send_email_always_uses_to_email(settings):
    r = respx.post("https://api.resend.com/emails").respond(200, json={"id": "x"})
    send_email("s", "b", "Someone <x@y.com>", settings=settings, client=httpx.Client())
    assert json.loads(r.calls[0].request.content)["to"] == [settings.to_email]


@respx.mock
def test_one_bad_domain_does_not_stop_batch_and_errors_are_scrubbed(settings, icp, proofs):
    mock_world()
    llm = FakeLLM(handlers(icp, [GOOD_DRAFT]))

    class Boom:
        def json(self, *a, **k):
            raise RuntimeError("leaked %s" % settings.gemini_api_key)
        search = json

    d = deps_for(settings, icp, proofs, llm)
    d2 = deps_for(settings, icp, proofs, Boom())
    bad = process("acme.com", d2)
    assert bad["status"] == "failed" and settings.gemini_api_key not in json.dumps(bad)
    res = run_batch(["not a domain", "acme.com", "acme.com"], d)
    assert [t["status"] for t in res] == ["failed", "sent"]  # duplicate dropped, bad one did not stop the rest
    assert (settings.out_dir / "acme.com" / "trace.json").exists() and (settings.out_dir / "acme.com" / "report.md").exists()
    assert (settings.out_dir / "summary.md").exists()


def test_review_columns_survive_rerun(tmp_path, settings):
    f = tmp_path / "review.csv"
    tr = {"domain": "a.com", "status": "sent", "seconds": 5}
    write_review_csv(f, [tr])
    update_review(f, "a.com", {"stage": "replied", "lead_agrees": "yes", "notes": "good"})
    write_review_csv(f, [{**tr, "seconds": 9}])  # re-run
    assert read_review(f)["a.com"]["stage"] == "replied" and read_review(f)["a.com"]["notes"] == "good"
