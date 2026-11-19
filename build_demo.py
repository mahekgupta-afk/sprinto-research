#!/usr/bin/env python
"""Build the public read-only demo: web/ -> site/ plus a scrubbed snapshot of out/.

Removes contact emails, LinkedIn, inbox addresses, Gmail links, notes and errors. Masks any remaining
email-shaped text. REFUSES to build if an email or key-shaped string survives anywhere in site/.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from outbound.accounts import list_accounts
from outbound.config import ROOT
from outbound.report import load_traces

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+")
KEYLIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|\bre_[0-9A-Za-z_]{16,}|\bsk-[0-9A-Za-z]{20,}|\b[0-9a-f]{40}\b|\bgh[pousr]_[0-9A-Za-z]{30,}|api[_-]?key\s*[=:]\s*\S{8,})", re.I)
MASK = "[hidden]"


class BuildRefused(RuntimeError):
    pass


def mask(text: str) -> str:
    return EMAIL.sub(MASK, text)


def short_name(name: str) -> str:
    parts = (name or "").split()
    return parts[0] + (" %s." % parts[-1][0] if len(parts) > 1 else "") if parts else ""


def scrub_value(v):
    if isinstance(v, str):
        return mask(v)
    if isinstance(v, list):
        return [scrub_value(x) for x in v]
    if isinstance(v, dict):
        return {k: scrub_value(x) for k, x in v.items()}
    return v


def scrub_trace(tr: dict) -> dict:
    t = json.loads(json.dumps(tr))
    t.pop("error", None)
    for k in ("gmail_link", "send", "intended"):
        t.pop(k, None)
    t["human"] = {k: v for k, v in (t.get("human") or {}).items() if k != "notes"}
    c = t.get("contact")
    if c:
        c.pop("fallback", None)
        p = c.get("person")
        if p:
            c["person"] = {"name": short_name(p.get("name", "")), "title": p.get("title", ""), "role": p.get("role", ""),
                           "source": p.get("source", ""), "email": "", "linkedin": "", "confidence": None}
    if t.get("email"):
        for d in t["email"]["drafts"]:
            d["body"] = d["body"]
    return scrub_value(t)


def scrub_row(r: dict) -> dict:
    r = json.loads(json.dumps(r))
    if r.get("contact"):
        r["contact"] = {"name": short_name(r["contact"]["name"]), "title": r["contact"]["title"], "email": "", "linkedin": ""}
    r["human"] = {k: v for k, v in r.get("human", {}).items() if k != "notes"}
    return scrub_value(r)


def scan(site: Path) -> list:
    bad = []
    for f in site.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".json", ".html", ".js", ".css", ".txt", ".csv", ".md", ".svg"):
            text = f.read_text(errors="ignore")
            for rx, kind in ((EMAIL, "email"), (KEYLIKE, "key")):
                m = rx.search(text)
                if m:
                    bad.append("%s: %s-shaped string" % (f.relative_to(site), kind))
    return bad


def build(out_dir: Path, web_dir: Path, site_dir: Path) -> int:
    if site_dir.exists():
        shutil.rmtree(site_dir)
    shutil.copytree(web_dir, site_dir, ignore=shutil.ignore_patterns(".DS_Store"))
    data = site_dir / "data"
    (data / "account").mkdir(parents=True)
    rows = [scrub_row(r) for r in list_accounts(out_dir)]
    (data / "accounts.json").write_text(json.dumps(rows, indent=1))
    for tr in load_traces(out_dir):
        (data / "account" / (tr["domain"] + ".json")).write_text(json.dumps(scrub_trace(tr), indent=1))
    problems = scan(site_dir)
    if problems:
        shutil.rmtree(site_dir)
        raise BuildRefused("refusing to build, would publish: " + "; ".join(problems))
    return len(rows)


if __name__ == "__main__":
    try:
        n = build(ROOT / "out", ROOT / "web", ROOT / "site")
    except BuildRefused as e:
        print(e)
        sys.exit(1)
    print("built site/ with %d accounts" % n)
