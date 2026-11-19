"""Step 3: qualify. The LLM picks buckets and cites evidence; Python computes the score."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel

from .extract import Ledger
from .scrape import Outcome, Page


class SignalPick(BaseModel):
    signal: str
    bucket: str  # a bucket id, or "unknown"
    evidence_ids: List[str]


class DisqPick(BaseModel):
    reason: str  # not_software | sprinto_customer | too_large | too_small
    evidence_ids: List[str]


class QualifyOut(BaseModel):
    picks: List[SignalPick]
    disqualifiers: List[DisqPick]


def build_prompt(icp: dict, profile: dict, ledger: Ledger, coverage: Dict[str, str]) -> str:
    sigs = []
    for s in icp["signals"]:
        bs = "; ".join("%s=%s (%s)" % (b["id"], b["points"], b["when"]) for b in s["buckets"])
        sigs.append("- %s%s: %s Buckets: %s" % (s["id"], " [external]" if s.get("external") else "", s["question"], bs))
    ev = "\n".join('%s [%s] %s | "%s" (%s)' % (e["id"], e["topic"], e["claim"], e["quote"], e["url"])
                   for e in ledger.items) or "(no verified evidence)"
    cov = ", ".join("%s=%s" % (k, v) for k, v in coverage.items())
    return (
        "Score a company against Sprinto's ICP. You ONLY choose a bucket per signal and cite evidence IDs.\n"
        "Rules: any bucket worth points needs at least one evidence ID that supports it. If the evidence does not settle "
        "a signal, answer bucket=\"unknown\" with no evidence. External signals: if the evidence is silent, answer unknown. "
        "A page that is not OK (blocked, missing, empty) tells you nothing; never choose an 'absent' bucket from it.\n"
        "Also list disqualifiers only if evidence clearly shows: not_software, sprinto_customer, too_large (2000+ staff), too_small.\n"
        "Return picks[] for ALL %d signals and disqualifiers[].\n\nPROFILE: %s\nPAGE COVERAGE: %s\n\nSIGNALS:\n%s\n\nEVIDENCE:\n%s"
    ) % (len(icp["signals"]), profile, cov, "\n".join(sigs), ev)


def coverage_of(pages: Dict[str, Page]) -> Dict[str, str]:
    return {p: pg.outcome.value for p, pg in pages.items()}


def compute(icp: dict, picks: List[dict], disq: List[dict], ledger: Ledger, coverage: Dict[str, str],
            profile: dict, trust_text_urls: Optional[List[str]] = None) -> dict:
    """Pure maths. Returns score bounds, per-signal detail, caps, disqualifiers, verdict."""
    by_sig = {p["signal"]: p for p in picks}
    valid = ledger.ids()
    low = high = 0
    detail: List[dict] = []
    block_known: Dict[str, int] = {}
    block_unknown: Dict[str, int] = {}
    cert_bucket = None
    for s in icp["signals"]:
        pick = by_sig.get(s["id"], {"bucket": "unknown", "evidence_ids": []})
        ev = [e for e in pick.get("evidence_ids", []) if e in valid]
        bucket = next((b for b in s["buckets"] if b["id"] == pick["bucket"]), None)
        status, pts, why = "known", 0, ""
        if bucket is None:
            status, why = "unknown", "no bucket chosen"
        elif not ev:
            # no cited evidence: points are never awarded. A zero bucket is only trusted for
            # non-external signals whose required pages were all readable.
            needs = s.get("needs_pages", [])
            readable = all(coverage.get(p) == Outcome.OK.value for p in needs) if needs else True
            if bucket["points"] == 0 and not s.get("external") and readable:
                pts = 0
            else:
                status, why = "unknown", ("website silence on external signal" if s.get("external")
                                          else "no evidence or page unreadable")
        else:
            pts = bucket["points"]
        if status == "known":
            low += pts
            high += pts
            block_known[s["block"]] = block_known.get(s["block"], 0) + pts
            if s["id"] == "certification_status":
                cert_bucket = bucket["id"]
        else:
            high += s["max"]
            block_unknown[s["block"]] = block_unknown.get(s["block"], 0) + s["max"]
        detail.append({"signal": s["id"], "block": s["block"], "max": s["max"], "status": status, "points": pts if status == "known" else None,
                       "bucket": bucket["id"] if bucket and status == "known" else "unknown", "evidence_ids": ev if status == "known" else [],
                       "note": why, "external": bool(s.get("external"))})
    caps: List[dict] = []
    pull_known = block_known.get("upmarket_pull", 0)
    pull_unknown = block_unknown.get("upmarket_pull", 0)
    c1 = icp["caps"]["no_upmarket_pull"]
    if pull_known == 0:
        low = min(low, c1)
        if pull_unknown == 0:
            high = min(high, c1)
            caps.append({"cap": "no_upmarket_pull", "max": c1})
    c2 = icp["caps"]["mature_certifications"]
    if cert_bucket == "both_mature":
        low, high = min(low, c2), min(high, c2)
        caps.append({"cap": "mature_certifications", "max": c2})
    dq = disqualifiers(icp, disq, ledger, profile)
    return {"low": low, "high": high, "signals": detail, "caps": caps, "disqualifiers": dq,
            "verdict": verdict(icp, low, high, dq)}


def disqualifiers(icp: dict, disq: List[dict], ledger: Ledger, profile: dict) -> List[dict]:
    out: List[dict] = []
    valid = ledger.ids()
    hc = profile.get("headcount")
    rules = icp["disqualifiers"]
    for d in disq:
        ev = [e for e in d.get("evidence_ids", []) if e in valid]
        if d["reason"] in ("not_software", "sprinto_customer") and ev:
            out.append({"reason": d["reason"], "evidence_ids": ev})
    if isinstance(hc, int):
        if hc >= rules["max_headcount"]:
            out.append({"reason": "too_large", "evidence_ids": [], "detail": "headcount %d" % hc})
        elif hc < rules["min_headcount"]:
            out.append({"reason": "too_small", "evidence_ids": [], "detail": "headcount %d" % hc})
    if profile.get("product_type") in ("services", "hardware"):
        if not any(o["reason"] == "not_software" for o in out):
            out.append({"reason": "not_software", "evidence_ids": [], "detail": profile["product_type"]})
    return out


def sprinto_hosted(pages: Dict[str, Page]) -> Optional[str]:
    """Code-level check: a trust page served from Sprinto means they already are a customer."""
    for p in pages.values():
        if p.outcome == Outcome.OK and "sprinto" in (p.final_url or "").lower() and "sprinto.com" not in p.url:
            return p.final_url
    for path in ("/trust", "/security"):
        p = pages.get(path)
        if p and p.outcome == Outcome.OK and ("trust.sprinto.com" in p.text.lower() or "powered by sprinto" in p.text.lower()):
            return p.url
    return None


def verdict(icp: dict, low: int, high: int, dq: List[dict]) -> str:
    t = icp["thresholds"]
    if dq:
        return "DISQUALIFIED"
    if low >= t["priority"]:
        return "PRIORITY"
    if low >= t["qualify"]:
        return "QUALIFY"
    if low < t["qualify"] <= high:
        return "INSUFFICIENT_DATA"
    if high >= 40:
        return "NURTURE"
    return "REJECT"


def qualify(llm, icp: dict, profile: dict, ledger: Ledger, pages: Dict[str, Page]) -> dict:
    cov = coverage_of(pages)
    out = llm.json(build_prompt(icp, profile, ledger, cov), QualifyOut)
    disq = list(out["disqualifiers"])
    hosted = sprinto_hosted(pages)
    res = compute(icp, out["picks"], disq, ledger, cov, profile)
    if hosted and not any(d["reason"] == "sprinto_customer" for d in res["disqualifiers"]):
        res["disqualifiers"].append({"reason": "sprinto_customer", "evidence_ids": [], "detail": hosted})
        res["verdict"] = "DISQUALIFIED"
    res["picks"] = out["picks"]
    res["raw_disqualifiers"] = out["disqualifiers"]
    return res
