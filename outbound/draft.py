"""Steps 7 and 8b: draft, validate in code, review with AI, rewrite. Up to 4 drafts."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel

from .extract import Ledger
from .validate import validate

MAX_DRAFTS = 4
MIN_SCORE = 7


class DraftOut(BaseModel):
    subject: str
    body: str
    hook_evidence_id: str
    proof_line: str


class ReviewOut(BaseModel):
    specificity: int
    relevance: int
    reply_likelihood: int
    critique: str


def prompt_for(ctx: dict, person: dict, pains: List[dict], feedback: Optional[str], prev: Optional[dict], preferences: Optional[List[str]] = None) -> str:
    ev = "\n".join('%s [%s]: %s | "%s"' % (e["id"], e["topic"], e["claim"], e["quote"]) for e in ctx["evidence"])
    pn = "\n".join("- %s (evidence %s; data: %s; buyer: %s)" % (p["pain"], ",".join(p["evidence_ids"]), p["data_handled"], p["buyer"]) for p in pains)
    proofs = "\n".join("- " + p for p in ctx["proof_lines"])
    s = (
        "Write a cold email from a Sprinto growth lead to %s (%s) at %s.\n"
        "Company: %s\nEvidence (only source of facts about them):\n%s\nPain points:\n%s\n"
        "Proof lines (use EXACTLY one, verbatim, copy into proof_line and body):\n%s\n\n"
        "Hard rules: max 110 words. Exactly one question mark and it ends the email, a specific question. No exclamation marks. "
        "No greeting line (do not start with Hi/Hello/Dear); address them by first name inside the first or second sentence. "
        "No markdown, lists or placeholders. Digits only for numbers that appear in the evidence or proof line; never spell numbers out. "
        "First sentence joins what they sell with ONE hook from the evidence (set hook_evidence_id). Subject: the company name plus a hook or product word. "
        "Never mention how you found information (no 'your website', 'endpoint', 'page'). At most one hedge word. Never list three frameworks. "
        "Do not use 'recent' unless the evidence is dated funding within 6 months. No sign-off or signature.\n"
        % (person.get("name") or "the founder", person.get("title") or "decision-maker", ctx["company"], ctx["profile"].get("one_liner"), ev, pn, proofs))
    if preferences:
        s += "\nReviewer preferences learned from past edits (secondary: the hard rules above always win):\n" + "\n".join("- " + p for p in preferences) + "\n"
    if feedback and prev:
        s += "\nPrevious draft:\nSubject: %s\n%s\nFix these problems and rewrite:\n%s\n" % (prev["subject"], prev["body"], feedback)
    return s


def review(llm, ctx: dict, d: dict) -> dict:
    prompt = (
        "You are a skeptical buyer at %s reviewing a cold email. Score 0-10: specificity (could only be written to this company), "
        "relevance (to their real compliance needs), reply_likelihood. Give a short critique with concrete fixes.\n\nSubject: %s\n%s\n\nEvidence:\n%s"
        % (ctx["company"], d["subject"], d["body"], "\n".join(e["quote"] for e in ctx["evidence"])))
    r = llm.json(prompt, ReviewOut)
    for k in ("specificity", "relevance", "reply_likelihood"):
        r[k] = max(0, min(10, int(r[k])))
    r["min"] = min(r["specificity"], r["relevance"], r["reply_likelihood"])
    r["avg"] = round((r["specificity"] + r["relevance"] + r["reply_likelihood"]) / 3, 1)
    return r


def make_ctx(company: str, person: dict, profile: dict, ledger: Ledger, proof_lines: List[str]) -> dict:
    name = (person.get("name") or "").strip()
    return {"company": company, "first_name": name.split()[0] if name else "", "profile": profile,
            "evidence": ledger.items, "proof_lines": proof_lines}


def write_email(llm, company: str, person: dict, profile: dict, pains: List[dict], ledger: Ledger,
                proof_lines: List[str], today=None, preferences: Optional[List[str]] = None) -> dict:
    ctx = make_ctx(company, person, profile, ledger, proof_lines)
    drafts: List[dict] = []
    feedback, prev = None, None
    for n in range(1, MAX_DRAFTS + 1):
        out = llm.json(prompt_for(ctx, person, pains, feedback, prev, preferences), DraftOut)
        out["body"] = out["body"].strip()
        fails = validate(out["subject"], out["body"], {**ctx, "hook_evidence_id": out["hook_evidence_id"],
                                                        "proof_line": out["proof_line"]}, today)
        d = {"n": n, **out, "code_failures": fails, "passed": not fails, "review": None}
        if not fails:
            d["review"] = review(llm, ctx, d)
        drafts.append(d)
        if d["passed"] and d["review"]["min"] >= MIN_SCORE:
            break
        feedback = "; ".join(fails) if fails else d["review"]["critique"]
        prev = d
    passing = [d for d in drafts if d["passed"]]
    best = max(passing, key=lambda d: d["review"]["avg"]) if passing else None
    return {"drafts": drafts, "best": best, "rewrites": len(drafts) - 1,
            "reviewer_ok": bool(best and best["review"]["min"] >= MIN_SCORE)}
