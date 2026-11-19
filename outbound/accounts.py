"""Shape trace.json into the rows the CRM shows. Used by app.py and build_demo.py."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .report import HUMAN_COLS, load_traces, read_review

DROP = {"not_qualified": "Screened out by the ICP score", "insufficient_data": "Not enough evidence to decide",
        "no_contact": "No decision-maker found", "held": "No draft passed validation", "failed": "Run failed", "sent": "", "pending_approval": "", "rejected": "Draft rejected by you"}


def stage_of(status: str, human: dict) -> str:
    if human.get("stage"):
        return human["stage"]
    if human.get("replied") == "yes":
        return "replied"
    return {"sent": "sent", "pending_approval": "approval", "rejected": "needs_you", "held": "needs_you", "no_contact": "needs_you", "failed": "needs_you"}.get(status, "screened_out")


def needs_you(tr: dict, human: dict) -> Optional[str]:
    st = tr["status"]
    if st == "pending_approval":
        return "Draft waiting for your approval"
    if st == "rejected":
        return "Draft rejected: rewrite or drop"
    if st == "held":
        return "Email held: no draft passed validation"
    if st == "no_contact":
        return "No contact found"
    if st == "failed":
        return "Run failed"
    if st == "insufficient_data" and any(p["outcome"] in ("BLOCKED", "TIMEOUT", "EMPTY_SHELL") for p in tr.get("scrape", [])):
        return "Site unreadable"
    if st == "sent" and not human.get("replied") and not human.get("stage"):
        return "Sent: log any reply"
    return None


def row_for(tr: dict, human: dict) -> dict:
    fin = tr.get("qualify_final") or {}
    fix = tr.get("qualify_fixed") or {}
    p = ((tr.get("contact") or {}).get("person")) or {}
    best = ((tr.get("email") or {}).get("best")) or {}
    scr = tr.get("scrape") or []
    ok = sum(1 for s in scr if s["outcome"] == "OK")
    return {
        "domain": tr["domain"], "company": (tr.get("profile") or {}).get("name") or tr["domain"],
        "one_liner": (tr.get("profile") or {}).get("one_liner", ""), "status": tr["status"],
        "verdict_fixed": tr.get("verdict_fixed", ""), "verdict_final": tr.get("verdict_final", ""),
        "fixed": [fix.get("low"), fix.get("high")], "final": [fin.get("low"), fin.get("high")],
        "overturned": bool(tr.get("verdict_fixed") and tr.get("verdict_fixed") != tr.get("verdict_final")),
        "pages_ok": ok, "pages_total": len(scr),
        "contact": {"name": p.get("name", ""), "title": p.get("title", ""), "email": p.get("email", ""), "linkedin": p.get("linkedin", "")} if p else None,
        "subject": best.get("subject", ""), "body_preview": (best.get("body") or "")[:140], "reviewer_avg": (best.get("review") or {}).get("avg"),
        "rewrites": (tr.get("email") or {}).get("rewrites"), "seconds": tr.get("seconds"),
        "drop_reason": DROP.get(tr["status"], ""), "stage": stage_of(tr["status"], human), "human": human,
        "needs": needs_you(tr, human), "synthetic": bool(tr.get("synthetic")),
    }


def list_accounts(out_dir: Path) -> List[dict]:
    rev = read_review(out_dir / "review.csv")
    return [row_for(t, rev.get(t["domain"], {h: "" for h in HUMAN_COLS})) for t in load_traces(out_dir)]
