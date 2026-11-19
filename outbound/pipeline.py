"""One company end to end. Every decision is written to trace.json."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx

from . import agent as agent_mod
from .config import Settings, clean_domain, scrub, valid_domain
from .contacts import Hunter, find_contact
from .approval import queue_draft
from .draft import write_email
from .feedback import retrieve
from .extract import Ledger, extract
from .pains import pains as make_pains
from .qualify import qualify
from .scrape import scrape_site
from .send import gmail_link, send_email

STATUSES = ("sent", "pending_approval", "rejected", "held", "not_qualified", "insufficient_data", "no_contact", "failed")


@dataclass
class Deps:
    settings: Settings
    llm: object
    http: httpx.Client
    hunter: Hunter
    icp: dict
    proof_lines: List[str]
    overrides: Dict[str, dict] = field(default_factory=dict)
    send: Callable = send_email


def process(domain: str, d: Deps) -> dict:
    domain = clean_domain(domain)
    t0 = time.monotonic()
    tr: dict = {"domain": domain, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "failed"}
    try:
        if not valid_domain(domain):
            raise ValueError("not a valid domain")
        _run(domain, d, tr)
    except Exception as e:  # noqa: BLE001  one bad domain never stops the batch
        tr["status"] = "failed"
        tr["error"] = scrub("%s: %s" % (type(e).__name__, e), d.settings)
    tr["seconds"] = round(time.monotonic() - t0, 1)
    return tr


def _run(domain: str, d: Deps, tr: dict) -> None:
    pages = scrape_site(d.http, domain)
    tr["scrape"] = [p.trace() for p in pages.values()]
    ledger = Ledger()
    profile = extract(d.llm, domain, pages, ledger) or {}
    tr["profile"] = profile
    res = qualify(d.llm, d.icp, profile, ledger, pages)
    tr["qualify_fixed"] = _slim(res)
    loop = agent_mod.run_agent(d.llm, d.http, domain, d.icp, profile, ledger, pages, res)
    res = loop["result"]
    tr["agent"] = {k: v for k, v in loop.items() if k != "result"}
    tr["qualify_final"] = _slim(res)
    tr["verdict_fixed"], tr["verdict_final"] = tr["qualify_fixed"]["verdict"], res["verdict"]
    tr["evidence"], tr["rejected_facts"] = ledger.items, ledger.rejected
    tr["profile"] = profile
    v = res["verdict"]
    if v == "INSUFFICIENT_DATA":
        tr["status"] = "insufficient_data"
        return
    if v not in ("PRIORITY", "QUALIFY"):
        tr["status"] = "not_qualified"
        return
    company = profile.get("name") or domain
    c = find_contact(d.llm, d.hunter, domain, company, profile.get("headcount"), d.overrides)
    tr["contact"] = c
    if not c["person"]:
        tr["status"] = "no_contact"
        return
    person = c["person"]
    tr["pains"] = make_pains(d.llm, profile, person, ledger)
    prefs = retrieve(d.settings.db_path) if d.settings.require_approval or d.settings.db_path.exists() else []
    em = write_email(d.llm, company, person, profile, tr["pains"], ledger, d.proof_lines, preferences=prefs)
    tr["email"] = em
    best = em["best"]
    if not best:
        tr["status"] = "held"  # nothing passed validation: NOTHING is sent
        return
    intended = "%s <%s>, %s at %s" % (person.get("name"), person.get("email"), person.get("title"), company)
    tr["intended"] = intended
    tr["gmail_link"] = gmail_link(d.settings, best["subject"], best["body"], intended)
    if d.settings.require_approval:
        queue_draft(d.settings.db_path, domain, best["subject"], best["body"])
        tr["status"] = "pending_approval"
        return
    tr["send"] = d.send(best["subject"], best["body"], intended, settings=d.settings, client=d.http)
    tr["status"] = "sent"


def _slim(res: dict) -> dict:
    return {k: res[k] for k in ("low", "high", "signals", "caps", "disqualifiers", "verdict")}


def write_trace(out_dir: Path, tr: dict) -> Path:
    p = out_dir / tr["domain"]
    p.mkdir(parents=True, exist_ok=True)
    (p / "trace.json").write_text(json.dumps(tr, indent=2, default=str))
    return p
