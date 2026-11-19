"""Human approval gate. Nothing is sent until a person approves; edits are re-validated; feedback is captured."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

from . import feedback
from .config import Settings, valid_domain
from .db import connect, now
from .send import gmail_link, send_email
from .validate import validate


class ApprovalError(Exception):
    def __init__(self, msg: str, failures: Optional[List[str]] = None, code: int = 400):
        super().__init__(msg)
        self.failures, self.code = failures or [], code


def queue_draft(db: Path, domain: str, subject: str, body: str) -> int:
    with connect(db) as c:
        c.execute("UPDATE drafts SET status='rejected', note='superseded by a newer draft', decided_at=? WHERE domain=? AND status='pending'", (now(), domain))
        cur = c.execute("INSERT INTO drafts(domain,subject,body,original_subject,original_body,created_at) VALUES(?,?,?,?,?,?)",
                        (domain, subject, body, subject, body, now()))
        return cur.lastrowid


def approval_of(db: Path, domain: str) -> Optional[dict]:
    with connect(db) as c:
        r = c.execute("SELECT * FROM drafts WHERE domain=? ORDER BY id DESC LIMIT 1", (domain,)).fetchone()
    return dict(r) if r else None


def _trace_path(out_dir: Path, domain: str) -> Path:
    if not valid_domain(domain):
        raise ApprovalError("bad domain", code=400)
    return Path(out_dir) / domain / "trace.json"


def _pending(db: Path, domain: str) -> dict:
    with connect(db) as c:
        r = c.execute("SELECT * FROM drafts WHERE domain=? AND status='pending' ORDER BY id DESC LIMIT 1", (domain,)).fetchone()
    if not r:
        raise ApprovalError("no draft is waiting for approval", code=409)
    return dict(r)


def approve(settings: Settings, http, domain: str, subject: str, body: str, rating: Optional[int] = None, note: str = "",
            sender: Callable = send_email, today: Optional[date] = None) -> dict:
    tp = _trace_path(settings.out_dir, domain)
    if not tp.exists():
        raise ApprovalError("unknown account", code=404)
    draft = _pending(settings.db_path, domain)
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        raise ApprovalError("rating must be 1 to 5")
    subject, body, note = subject.strip(), body.strip(), (note or "")[:500]
    if not subject or not body or len(body) > 3000:
        raise ApprovalError("subject and body are required")
    tr = json.loads(tp.read_text())
    best = tr["email"]["best"]
    person = tr["contact"]["person"]
    ctx = {"company": (tr.get("profile") or {}).get("name") or domain, "first_name": (person.get("name") or "").split()[0] if person.get("name") else "",
           "profile": tr.get("profile") or {}, "evidence": tr["evidence"], "proof_lines": _proofs(settings),
           "hook_evidence_id": best["hook_evidence_id"], "proof_line": best["proof_line"]}
    fails = validate(subject, body, ctx, today)
    if fails:
        raise ApprovalError("your edit breaks the rules, so it was not sent", fails)
    res = sender(subject, body, tr["intended"], settings=settings, client=http)  # always TO_EMAIL
    with connect(settings.db_path) as c:
        c.execute("UPDATE drafts SET status='sent', subject=?, body=?, rating=?, note=?, decided_at=?, send_id=? WHERE id=?",
                  (subject, body, rating, note, now(), str(res.get("id")), draft["id"]))
    feedback.capture(settings.db_path, domain, draft["original_subject"], draft["original_body"], subject, body, rating, note)
    best["subject"], best["body"] = subject, body
    tr["email"]["edited"] = (draft["original_subject"], draft["original_body"]) != (subject, body)
    tr["send"], tr["status"] = res, "sent"
    tr["gmail_link"] = gmail_link(settings, subject, body, tr["intended"])
    tp.write_text(json.dumps(tr, indent=2, default=str))
    return {"status": "sent", "edited": tr["email"]["edited"]}


def reject(settings: Settings, domain: str, reason: str = "", rating: Optional[int] = None) -> dict:
    tp = _trace_path(settings.out_dir, domain)
    if not tp.exists():
        raise ApprovalError("unknown account", code=404)
    draft = _pending(settings.db_path, domain)
    with connect(settings.db_path) as c:
        c.execute("UPDATE drafts SET status='rejected', note=?, rating=?, decided_at=? WHERE id=?", (reason[:500], rating, now(), draft["id"]))
    if reason or rating is not None:
        feedback.capture(settings.db_path, domain, draft["original_subject"], draft["original_body"], draft["original_subject"], draft["original_body"],
                         rating, "Rejected: " + reason)
    tr = json.loads(tp.read_text())
    tr["status"] = "rejected"
    tp.write_text(json.dumps(tr, indent=2, default=str))
    return {"status": "rejected"}


def _proofs(settings: Settings) -> List[str]:
    from .config import load_proof_lines
    return load_proof_lines()
