import httpx
import respx

from conftest import FakeLLM, LONG, html
from outbound import agent
from outbound.extract import Ledger
from outbound.qualify import compute, verdict, qualify
from outbound.scrape import Outcome, Page


def ledger_with(n=3):
    led = Ledger()
    for i in range(n):
        led.items.append({"id": "E%d" % (i + 1), "topic": "x", "claim": "c", "quote": "q%d" % i, "url": "u", "date": None, "verified": True})
    return led


OK_ALL = {p: Outcome.OK.value for p in ["/", "/pricing", "/security", "/trust", "/customers", "/about", "/careers"]}


def picks(icp, **over):
    """Every signal best bucket with E1 unless overridden by id -> (bucket, evidence)."""
    out = []
    for s in icp["signals"]:
        best = max(s["buckets"], key=lambda b: b["points"])
        b, ev = over.get(s["id"], (best["id"], ["E1"]))
        out.append({"signal": s["id"], "bucket": b, "evidence_ids": ev})
    return out


def test_full_marks_is_100(icp):
    r = compute(icp, picks(icp), [], ledger_with(), OK_ALL, {})
    assert (r["low"], r["high"]) == (100, 100) and r["verdict"] == "PRIORITY"


def test_points_need_valid_evidence(icp):
    r = compute(icp, picks(icp, b2b_model=("b2b", ["E99"])), [], ledger_with(), OK_ALL, {})
    s = next(x for x in r["signals"] if x["signal"] == "b2b_model")
    assert s["status"] == "unknown" and r["low"] == 94 and r["high"] == 100


def test_unknown_widens_range(icp):
    r = compute(icp, picks(icp, headcount=("unknown", []), funding_stage=("unknown", [])), [], ledger_with(), OK_ALL, {})
    assert r["low"] == 82 and r["high"] == 100


def test_website_silence_on_external_signal_is_unknown_not_absent(icp):
    # zero bucket without evidence on an external signal must not be treated as a known zero
    r = compute(icp, picks(icp, security_hiring=("not_hiring", [])), [], ledger_with(), OK_ALL, {})
    s = next(x for x in r["signals"] if x["signal"] == "security_hiring")
    assert s["status"] == "unknown" and r["high"] == 100 and r["low"] == 94


def test_absent_requires_readable_pages(icp):
    cov = dict(OK_ALL, **{"/security": "BLOCKED"})
    p = picks(icp, security_page_gap=("strong", []))
    r = compute(icp, p, [], ledger_with(), cov, {})
    s = next(x for x in r["signals"] if x["signal"] == "security_page_gap")
    assert s["status"] == "unknown"
    r2 = compute(icp, p, [], ledger_with(), OK_ALL, {})
    assert next(x for x in r2["signals"] if x["signal"] == "security_page_gap")["status"] == "known"


def test_cap_no_upmarket_pull(icp):
    p = picks(icp, enterprise_customers=("absent", []), enterprise_motion=("self_serve_only", []), regulated_buyers=("absent", []))
    r = compute(icp, p, [], ledger_with(), OK_ALL, {})
    assert r["high"] == 55 and r["low"] == 55 and r["caps"][0]["cap"] == "no_upmarket_pull"
    assert r["verdict"] == "NURTURE"


def test_cap_mature_certs(icp):
    r = compute(icp, picks(icp, certification_status=("both_mature", ["E1"])), [], ledger_with(), OK_ALL, {})
    assert r["high"] == 40 and r["low"] == 40 and r["verdict"] == "NURTURE"


def test_disqualifiers(icp):
    r = compute(icp, picks(icp), [], ledger_with(), OK_ALL, {"headcount": 5000, "product_type": "software"})
    assert r["verdict"] == "DISQUALIFIED" and r["disqualifiers"][0]["reason"] == "too_large"
    r = compute(icp, picks(icp), [], ledger_with(), OK_ALL, {"headcount": 2, "product_type": "software"})
    assert r["disqualifiers"][0]["reason"] == "too_small"
    r = compute(icp, picks(icp), [], ledger_with(), OK_ALL, {"product_type": "services"})
    assert r["disqualifiers"][0]["reason"] == "not_software"
    r = compute(icp, picks(icp), [{"reason": "sprinto_customer", "evidence_ids": ["E1"]}], ledger_with(), OK_ALL, {"product_type": "software"})
    assert r["verdict"] == "DISQUALIFIED"
    r = compute(icp, picks(icp), [{"reason": "sprinto_customer", "evidence_ids": []}], ledger_with(), OK_ALL, {"product_type": "software"})
    assert r["verdict"] == "PRIORITY"  # uncited claim is ignored


def test_sprinto_hosted_trust_page_disqualifies(icp):
    pages = {"/trust": Page("/trust", "https://a.com/trust", Outcome.OK, 200, "Powered by Sprinto trust center " * 10)}
    llm = FakeLLM({"QualifyOut": {"picks": [], "disqualifiers": []}})
    r = qualify(llm, icp, {"product_type": "software"}, Ledger(), pages)
    assert r["verdict"] == "DISQUALIFIED" and r["disqualifiers"][0]["reason"] == "sprinto_customer"


def test_verdict_buckets(icp):
    assert verdict(icp, 80, 80, []) == "PRIORITY" and verdict(icp, 60, 60, []) == "QUALIFY"
    assert verdict(icp, 40, 70, []) == "INSUFFICIENT_DATA" and verdict(icp, 30, 50, []) == "NURTURE"
    assert verdict(icp, 10, 30, []) == "REJECT"


# ---- agent loop ----
def uncertain_pick(icp):
    # headcount + funding unknown, the rest best -> [82,100]? make it straddle 60
    out = []
    for s in icp["signals"]:
        out.append({"signal": s["id"], "bucket": "unknown", "evidence_ids": []})
    return out


class Planner:
    def __init__(self, choices):
        self.choices = list(choices)

    def __call__(self, prompt):
        return self.choices.pop(0) if len(self.choices) > 1 else self.choices[0]


def base_res(icp):
    return compute(icp, uncertain_pick(icp), [], Ledger(), {}, {"product_type": "software"})


@respx.mock
def test_agent_stops_at_tool_budget_and_refuses_repeats(icp):
    respx.get(url__regex=r"https://a\.com/.*").respond(404)
    llm = FakeLLM({"ToolChoice": {"tool": "fetch_page", "argument": "/pricing", "reason": "r"},
                   "ExtractOut": {"facts": [], "profile": {"name": "A", "one_liner": "x", "product_type": "software"}},
                   "QualifyOut": {"picks": [], "disqualifiers": []}})
    out = agent.run_agent(llm, httpx.Client(), "a.com", icp, {"product_type": "software"}, Ledger(), {}, base_res(icp))
    assert out["tool_calls"] == 4
    assert any(s.get("error") == "repeat refused" for s in out["steps"])
    assert out["steps"][-1]["stopped"] == "tool budget used"


def test_agent_search_budget_and_allowlist(icp):
    llm = FakeLLM({"ToolChoice": [{"tool": "web_research", "argument": "q1", "reason": "r"}, {"tool": "web_research", "argument": "q2", "reason": "r"},
                                  {"tool": "web_research", "argument": "q3", "reason": "r"}, {"tool": "fetch_page", "argument": "/admin", "reason": "r"}],
                   "ExtractOut": {"facts": [], "profile": {"name": "A", "one_liner": "x", "product_type": "software"}},
                   "QualifyOut": {"picks": [], "disqualifiers": []}}, search_text="nothing useful")
    out = agent.run_agent(llm, httpx.Client(), "a.com", icp, {"product_type": "software"}, Ledger(), {}, base_res(icp))
    assert len(llm.searches) == 2
    errs = [s.get("error") for s in out["steps"]]
    assert "search budget used" in errs and "path not allow-listed" in errs


def test_agent_time_budget(icp):
    t = iter([0, 500])
    llm = FakeLLM({"ToolChoice": {"tool": "web_research", "argument": "q", "reason": "r"}})
    out = agent.run_agent(llm, httpx.Client(), "a.com", icp, {}, Ledger(), {}, base_res(icp), clock=lambda: next(t, 999))
    assert out["steps"][-1]["stopped"] == "time budget used" and out["tool_calls"] == 0


def test_agent_does_not_run_when_certain(icp):
    res = compute(icp, picks(icp), [], ledger_with(), OK_ALL, {})
    llm = FakeLLM({})
    out = agent.run_agent(llm, httpx.Client(), "a.com", icp, {}, ledger_with(), {}, res)
    assert out["steps"] == [] and llm.calls == 0


def test_agent_overturns_verdict_with_research(icp):
    # grounded research finds evidence -> LLM re-picks buckets -> score jumps over the line
    best = picks(icp)
    llm = FakeLLM({"ToolChoice": {"tool": "web_research", "argument": "acme funding", "reason": "funding unknown"},
                   "ExtractOut": {"facts": [{"topic": "funding", "claim": "raised", "quote": "Acme raised a Series A last spring", "url": "web_research:acme funding"}],
                                  "profile": {"name": "Acme", "one_liner": "x", "product_type": "software"}},
                   "QualifyOut": {"picks": best, "disqualifiers": []}}, search_text="Acme raised a Series A last spring, per news.")
    led = Ledger()
    led.items.append({"id": "E1", "topic": "x", "claim": "c", "quote": "q", "url": "u", "date": None, "verified": True})
    start = compute(icp, uncertain_pick(icp), [], led, {}, {"product_type": "software"})
    assert start["verdict"] == "INSUFFICIENT_DATA"
    out = agent.run_agent(llm, httpx.Client(), "a.com", icp, {"product_type": "software"}, led, {}, start)
    assert out["result"]["verdict"] == "PRIORITY" and out["steps"][0]["new_evidence"] == 1
    assert out["steps"][0]["before"] == [start["low"], start["high"]]


@respx.mock
def test_job_postings_boards():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(200, json={"jobs": [{"title": "Security Engineer"}]})
    t = agent.job_postings(httpx.Client(), "acme")
    assert "Security Engineer" in t
    respx.get("https://boards-api.greenhouse.io/v1/boards/none/jobs").respond(404)
    respx.get("https://api.lever.co/v0/postings/none?mode=json").respond(404)
    respx.get("https://api.ashbyhq.com/posting-api/job-board/none").respond(404)
    assert agent.job_postings(httpx.Client(), "none") is None
