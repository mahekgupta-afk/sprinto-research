#!/usr/bin/env python
"""Write SYNTHETIC example data to out/ so the CRM can be developed and shown without API keys.

Every company is fictional (.test domains) and every trace carries "synthetic": true.
Usage: python scripts/make_sample_data.py [out_dir]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outbound.config import load_icp  # noqa: E402
from outbound.extract import Ledger  # noqa: E402
from outbound.pipeline import write_trace  # noqa: E402
from outbound.qualify import compute  # noqa: E402
from outbound.report import write_reports, load_traces, update_review  # noqa: E402

ICP = load_icp()
PATHS = ["/", "/pricing", "/security", "/trust", "/customers", "/about", "/careers"]
BEST = {s["id"]: max(s["buckets"], key=lambda b: b["points"])["id"] for s in ICP["signals"]}


def bucket_for(sig, level):
    bs = sorted(sig["buckets"], key=lambda b: -b["points"])
    return bs[0]["id"] if level == "hi" else (bs[min(1, len(bs) - 1)]["id"] if level == "mid" else bs[-1]["id"])


def score(base, buckets, unknown, ledger, cov, profile, disq=()):
    picks = []
    for s in ICP["signals"]:
        if s["id"] in unknown:
            picks.append({"signal": s["id"], "bucket": "unknown", "evidence_ids": []})
        else:
            picks.append({"signal": s["id"], "bucket": buckets.get(s["id"], bucket_for(s, base)), "evidence_ids": ["E1"]})
    r = compute(ICP, picks, list(disq), ledger, cov, profile)
    return {k: r[k] for k in ("low", "high", "signals", "caps", "disqualifiers", "verdict")}


def ledger_of(items):
    led = Ledger()
    for i, (topic, claim, quote) in enumerate(items, 1):
        led.items.append({"id": "E%d" % i, "topic": topic, "claim": claim, "quote": quote, "url": "https://example.test/", "date": None, "verified": True, "source": "page"})
    return led


def email(subject, body, avg, spec=(8, 8, 8), rewrites=0, crit="Specific hook, one clear question."):
    d = {"n": rewrites + 1, "subject": subject, "body": body, "hook_evidence_id": "E1", "proof_line": PROOF, "code_failures": [], "passed": True,
         "review": {"specificity": spec[0], "relevance": spec[1], "reply_likelihood": spec[2], "critique": crit, "min": min(spec), "avg": avg}}
    return {"drafts": [d], "best": d, "rewrites": rewrites, "reviewer_ok": True}


PROOF = "Sprinto automates evidence collection for SOC 2 and ISO 27001 by connecting to cloud, HR and engineering tools."

ALL = [x["id"] for x in ICP["signals"]]
COMPANIES = [
    dict(domain="ledgerloop.test", name="LedgerLoop", one="payments reconciliation API for fintech platforms", hc=45, secs=61.2, status="sent", base="hi",
         ev=[("customers", "Serves licensed lenders and neobanks", "Reconciliation for licensed lenders and neobanks"), ("security", "No audit report listed", "Security reports available on request"), ("funding", "Seed round announced", "Backed by a seed round led by Foundry Ten")],
         buckets={"headcount": "sweet_spot", "funding_stage": "seed_to_b", "recent_funding": "old", "enterprise_customers": "named_smb", "enterprise_motion": "self_serve_only", "regulated_buyers": "absent",
                  "certification_status": "none", "security_page_gap": "thin_or_request", "sensitive_data": "medium"},
         stay_unknown=["security_hiring"],
         steps=[dict(tool="fetch_page", argument="/customers", reason="customer proof unknown", reveals=["enterprise_customers", "enterprise_motion"]),
                dict(tool="web_research", argument="LedgerLoop funding stage employees", reason="funding and headcount are external", reveals=["headcount", "funding_stage", "recent_funding"])],
         person=dict(name="Maya Okafor", title="Co-founder & CEO", email="maya@ledgerloop.test", role="founder", source="hunter.domain_search"),
         subject="LedgerLoop reconciliation for lenders and neobanks", reviewer=(9, 8, 8), avg=8.3, rewrites=1,
         body="Maya, reconciliation for licensed lenders and neobanks means every new bank partner asks how you protect their ledgers.\n\n" + PROOF + "\n\nWould a SOC 2 report this year shorten your next partner security review?"),
    dict(domain="carepath.test", name="CarePath", one="telehealth scheduling for specialist clinics", hc=120, secs=48.0, status="pending_approval", base="hi",
         ev=[("data_handled", "Handles patient appointment data", "Patient intake and appointment records stay in one place"), ("customers", "Hospital networks", "Used by three regional hospital networks"), ("security", "HIPAA mentioned", "We take HIPAA seriously")],
         buckets={"certification_status": "type1_or_one", "recent_funding": "old"}, stay_unknown=[], steps=[],
         person=dict(name="Dev Raman", title="Head of Security", email="dev@carepath.test", role="security", source="hunter.domain_search"),
         subject="CarePath patient scheduling and HIPAA proof", reviewer=(8, 9, 7), avg=8.0, rewrites=0,
         body="Dev, scheduling patient intake across specialist clinics puts appointment records in front of every hospital security team.\n\n" + PROOF + "\n\nWho on your side answers the hospital questionnaires today?"),
    dict(domain="northwind-dev.test", name="Northwind Dev", one="CI pipeline analytics for engineering teams", hc=60, secs=39.5, status="not_qualified", base="hi",
         ev=[("product", "Self-serve developer tool", "Start free, pay by seat with a card")], buckets={"enterprise_customers": "absent", "enterprise_motion": "self_serve_only", "regulated_buyers": "absent"}, steps=[]),
    dict(domain="brightcart.test", name="BrightCart", one="consumer storefront for handmade goods", hc=15, secs=22.1, status="not_qualified", base="lo",
         ev=[("product", "Consumer marketplace", "Shop handmade gifts for friends and family")], buckets={"b2b_model": "absent", "certification_status": "none"},
         steps=[dict(tool="web_research", argument="BrightCart employees", reason="headcount unknown", reveals=["headcount"])]),
    dict(domain="vaultly.test", name="Vaultly", one="secrets management for platform teams", hc=210, secs=57.3, status="not_qualified", base="hi",
         ev=[("compliance", "SOC 2 Type II and ISO 27001", "SOC 2 Type II and ISO 27001 certified")], buckets={"certification_status": "both_mature", "security_page_gap": "strong"}, steps=[]),
    dict(domain="megacorp.test", name="MegaCorp Systems", one="enterprise ERP suites", hc=5200, secs=18.0, status="not_qualified", base="hi",
         ev=[("headcount", "5,200 employees", "Our 5,200 employees serve customers in 40 countries")], buckets={}, steps=[]),
    dict(domain="tracewire.test", name="Tracewire", one="observability for data pipelines", hc=None, secs=44.9, status="insufficient_data", blocked=True, base="mid",
         ev=[], buckets={}, stay_unknown=ALL,
         steps=[dict(tool="web_research", argument="Tracewire data pipeline observability company", reason="site blocked, need basics", reveals=[]),
                dict(tool="job_postings", argument="tracewire", reason="security hiring is external", reveals=[], outcome="NOT_FOUND")]),
    dict(domain="paylattice.test", name="PayLattice", one="invoice financing for freight carriers", hc=80, secs=71.8, status="no_contact", base="hi",
         ev=[("customers", "Freight carriers and brokers", "Financing for freight carriers and brokers"), ("data_handled", "Bank details", "We store carrier bank details and invoices")],
         buckets={"certification_status": "in_progress"}, stay_unknown=["funding_stage"], steps=[], person=None),
    dict(domain="skylane.test", name="Skylane", one="route planning software for regional airlines", hc=95, secs=83.4, status="held", base="hi",
         ev=[("customers", "Regional airlines", "Route planning for regional airlines"), ("security", "Security page thin", "Contact us for security documentation")],
         buckets={"certification_status": "none", "enterprise_customers": "named_enterprise", "enterprise_motion": "enterprise_plan"}, steps=[],
         person=dict(name="Ines Duarte", title="CTO", email="ines@skylane.test", role="cto", source="hunter.domain_search")),
    dict(domain="quillhr.test", name="QuillHR", one="onboarding workflows for HR teams", hc=70, secs=66.0, status="not_qualified", base="mid",
         ev=[("product", "HR onboarding forms", "Onboarding workflows for HR teams of any size"), ("security", "SOC 2 Type II", "SOC 2 Type II audited annually")],
         buckets={"certification_status": "type2_only", "enterprise_customers": "named_smb", "enterprise_motion": "self_serve_only", "regulated_buyers": "absent", "headcount": "sweet_spot", "funding_stage": "bootstrapped_or_other", "security_page_gap": "strong", "sensitive_data": "low"},
         stay_unknown=["recent_funding", "security_hiring"],
         steps=[dict(tool="fetch_page", argument="/trust", reason="certification posture unknown", reveals=["certification_status", "security_page_gap"]),
                dict(tool="fetch_page", argument="/customers", reason="customer size unknown", reveals=["enterprise_customers", "enterprise_motion", "regulated_buyers"])]),
    dict(domain="orbitdesk.test", name="OrbitDesk", one="helpdesk software for regulated lenders", hc=150, secs=52.6, status="sent", base="hi",
         ev=[("customers", "Regulated lenders", "Helpdesk built for regulated lenders and credit unions"), ("security", "Security review friction", "Download our security whitepaper after a call with sales")],
         buckets={"certification_status": "none", "recent_funding": "old"}, steps=[],
         person=dict(name="Tom Becker", title="VP Engineering", email="tom@orbitdesk.test", role="cto", source="hunter.domain_search"),
         subject="OrbitDesk helpdesk for lenders and credit unions", reviewer=(9, 9, 8), avg=8.7, rewrites=0, human={"stage": "replied", "replied": "yes", "lead_agrees": "yes", "edit_level": "none", "notes": "Asked about timeline for SOC 2. Booked a call."},
         body="Tom, a helpdesk for regulated lenders and credit unions means each new lender asks for security proof before signing.\n\n" + PROOF + "\n\nWhat happens to a lender deal today when the report is not ready?"),
]


def trace_for(c):
    blocked = c.get("blocked")
    cov = {p: ("BLOCKED" if blocked else ("OK" if p in ("/", "/pricing", "/security", "/trust", "/customers") else "NOT_FOUND")) for p in PATHS}
    led = ledger_of(c["ev"])
    profile = {"name": c["name"], "one_liner": c["one"], "product_type": "software", "headcount": c["hc"]}
    base, bk = c.get("base", "mid"), c["buckets"]
    reveals = [s["reveals"] for s in c["steps"]]
    never = list(c.get("stay_unknown", []))
    unknown = set(never) | {x for r in reveals for x in r}
    fixed = score(base, bk, unknown, led, cov, profile)
    stages, steps = [fixed], []
    for s, r in zip(c["steps"], reveals):
        unknown -= set(r)
        stages.append(score(base, bk, unknown, led, cov, profile))
        st = {"tool": s["tool"], "argument": s["argument"], "reason": s["reason"], "before": [stages[-2]["low"], stages[-2]["high"]],
              "after": [stages[-1]["low"], stages[-1]["high"]], "new_evidence": len(r)}
        if s.get("outcome"):
            st["outcome"] = s["outcome"]
        steps.append(st)
    final = stages[-1]
    status = c["status"]
    tr = {"domain": c["domain"], "synthetic": True, "started": "2026-11-17T09:00:00+00:00", "status": status, "seconds": c["secs"],
          "scrape": [{"path": p, "url": "https://%s%s" % (c["domain"], p), "outcome": cov[p], "status": 403 if blocked else (200 if cov[p] == "OK" else 404), "chars": 1800 if cov[p] == "OK" else 0, "final_url": ""} for p in PATHS],
          "profile": profile, "qualify_fixed": fixed, "qualify_final": final, "verdict_fixed": fixed["verdict"], "verdict_final": final["verdict"],
          "agent": {"steps": steps, "tool_calls": len(steps), "searches": sum(1 for s in steps if s["tool"] == "web_research"), "seconds": 20.0},
          "evidence": led.items, "rejected_facts": []}
    if status in ("sent", "pending_approval", "held", "no_contact"):
        order = ["founder", "cto"] if (c["hc"] or 0) <= 50 else (["security", "cto"] if (c["hc"] or 0) > 200 else ["security", "cto", "founder"])
        p = c.get("person")
        tr["contact"] = {"person": p, "order": order, "note": "Hunter titled match" if p else "no titled decision-maker and no findable email"}
    if status in ("sent", "pending_approval", "held"):
        tr["pains"] = [{"pain": "Buyers ask for audit proof before signing", "evidence_ids": ["E1"], "data_handled": c["ev"][0][1], "buyer": "regulated buyers"},
                       {"pain": "Security questionnaires pull engineers off product work", "evidence_ids": ["E2" if len(c["ev"]) > 1 else "E1"], "data_handled": "customer records", "buyer": "enterprise security teams"}]
    if status in ("sent", "pending_approval"):
        tr["email"] = email(c["subject"], c["body"], c["avg"], c["reviewer"], c["rewrites"])
        tr["intended"] = "%s <%s>, %s at %s" % (c["person"]["name"], c["person"]["email"], c["person"]["title"], c["name"])
        if status == "sent":
            tr["send"] = {"id": "synthetic", "to": "owner@example.test"}
    if status == "held":
        d = {"n": 1, "subject": "Skylane routes", "body": "Ines, route planning for regional airlines is hard. Why? How?", "hook_evidence_id": "E1", "proof_line": "", "code_failures": ["must contain exactly one question mark (has 2)", "proof line is not from sprinto_facts.md"], "passed": False, "review": None}
        tr["email"] = {"drafts": [dict(d, n=i) for i in range(1, 5)], "best": None, "rewrites": 3, "reviewer_ok": False}
    return tr


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for c in COMPANIES:
        write_trace(out, trace_for(c))
    write_reports(out, load_traces(out))
    from outbound.approval import queue_draft
    for c in COMPANIES:
        if c["status"] == "pending_approval":
            b = trace_for(c)["email"]["best"]
            queue_draft(out / "autopilot.db", c["domain"], b["subject"], b["body"])
    for c in COMPANIES:
        if c.get("human"):
            update_review(out / "review.csv", c["domain"], c["human"])
    print("wrote %d synthetic accounts to %s" % (len(COMPANIES), out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "out")
