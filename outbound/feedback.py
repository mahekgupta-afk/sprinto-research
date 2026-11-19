"""Feedback loop: capture the reviewer's edits and ratings, distil them into rules, feed them back into drafting."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import List

from pydantic import BaseModel

from .db import connect, now


class RulesOut(BaseModel):
    rules: List[str]


def capture(db: Path, domain: str, orig_subject: str, orig_body: str, subject: str, body: str,
            rating: int = None, note: str = "") -> int:
    n = 0
    with connect(db) as c:
        if (orig_subject, orig_body) != (subject, body):
            diff = "\n".join(l for l in difflib.unified_diff(orig_body.splitlines(), body.splitlines(), lineterm="", n=0)
                             if not l.startswith(("---", "+++", "@@")))
            txt = "Subject: %r -> %r\nBody changes:\n%s" % (orig_subject, subject, diff[:1200])
            c.execute("INSERT INTO learnings(kind,text,domain,created_at) VALUES('edit',?,?,?)", (txt, domain, now()))
            n += 1
        if rating is not None or note:
            c.execute("INSERT INTO learnings(kind,text,domain,created_at) VALUES('rating',?,?,?)",
                      ("Rated %s/5. %s" % (rating if rating is not None else "n/a", note.strip()[:500]), domain, now()))
            n += 1
    return n


def retrieve(db: Path, limit: int = 8) -> List[str]:
    """Active rules first, then the most recent raw edits and notes."""
    with connect(db) as c:
        rules = [r["text"] for r in c.execute("SELECT text FROM learnings WHERE kind='rule' AND active=1 ORDER BY id DESC LIMIT 5")]
        raw = [r["text"] for r in c.execute("SELECT text FROM learnings WHERE kind!='rule' ORDER BY id DESC LIMIT ?", (max(0, limit - len(rules)),))]
    return rules + raw


def learn(llm, db: Path) -> List[str]:
    """Distil recent edits and ratings into at most 5 short rules; older rules are retired."""
    with connect(db) as c:
        raw = [r["text"] for r in c.execute("SELECT text FROM learnings WHERE kind!='rule' ORDER BY id DESC LIMIT 25")]
    if not raw:
        return []
    out = llm.json("A reviewer edited and rated cold emails. Turn these into at most 5 short, general writing rules "
                   "(imperative, no company names). Ignore anything that would invent facts or break these hard rules: one question, "
                   "under 110 words, no greeting, no exclamation marks.\n\n" + "\n---\n".join(raw), RulesOut)
    rules = [r.strip() for r in out["rules"] if r.strip()][:5]
    with connect(db) as c:
        c.execute("UPDATE learnings SET active=0 WHERE kind='rule'")
        for r in rules:
            c.execute("INSERT INTO learnings(kind,text,created_at) VALUES('rule',?,?)", (r, now()))
    return rules
