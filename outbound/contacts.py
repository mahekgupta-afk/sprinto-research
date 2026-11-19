"""Step 5: find the right point of contact. Hunter first (cached), grounded search as fallback. Never invent."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel

from .config import Settings

HUNTER = "https://api.hunter.io/v2"
EXCLUDE = re.compile(r"\b(sales|marketing|market|hr|human resources|people|talent|recruit\w*|revenue|growth|sdr|bdr|"
                     r"business development|customer success|support|account (executive|manager)|brand|content|community|partnership\w*)\b", re.I)
ROLE_RX = {
    "security": re.compile(r"\b(ciso|chief information security|security|grc|compliance|risk|trust|privacy|infosec)\b", re.I),
    "cto": re.compile(r"\b(cto|chief technology|chief technical|vp (of )?engineering|head of engineering|vp eng)\b", re.I),
    "founder": re.compile(r"\b(founder|co-?founder|ceo|chief executive|owner|president)\b", re.I),
}


def role_order(headcount: Optional[int]) -> List[str]:
    if isinstance(headcount, int):
        if headcount <= 50:
            return ["founder", "cto"]
        if headcount > 200:
            return ["security", "cto"]
    return ["security", "cto", "founder"]  # 51-200 or unknown


def classify(position: str) -> Optional[str]:
    if not position or EXCLUDE.search(position):
        return None
    for role in ("security", "cto", "founder"):
        if ROLE_RX[role].search(position):
            return role
    return None


class Hunter:
    def __init__(self, settings: Settings, client: httpx.Client, cache_dir: Optional[Path] = None):
        self.s, self.client = settings, client
        self.cache = (cache_dir or settings.cache_dir) / "hunter"
        self.live_calls = 0

    def _get(self, kind: str, params: dict) -> dict:
        key = hashlib.sha1((kind + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:16]
        f = self.cache / ("%s_%s.json" % (kind, key))
        if f.exists():
            return json.loads(f.read_text())
        r = self.client.get("%s/%s" % (HUNTER, kind), params={**params, "api_key": self.s.hunter_api_key}, timeout=20)
        self.live_calls += 1
        if r.status_code == 404:
            data: dict = {"data": {}}
        else:
            r.raise_for_status()
            data = r.json()
        self.cache.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data))  # response only; the key is never part of the cached body
        return data

    def domain_search(self, domain: str) -> List[dict]:
        d = self._get("domain-search", {"domain": domain, "limit": 25}).get("data", {})
        return d.get("emails", []) or []

    def email_finder(self, domain: str, first: str, last: str) -> Optional[dict]:
        d = self._get("email-finder", {"domain": domain, "first_name": first, "last_name": last}).get("data", {})
        return d if d.get("email") else None


def _person(e: dict, role: str, domain: str, source: str) -> dict:
    name = ("%s %s" % (e.get("first_name") or "", e.get("last_name") or "")).strip()
    return {"name": name, "title": e.get("position") or "", "email": e.get("email") or "", "role": role,
            "linkedin": e.get("linkedin") or "", "confidence": e.get("confidence"), "source": source, "domain": domain}


def read_overrides(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    out: Dict[str, dict] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            d = (row.get("domain") or "").strip().lower()
            if d and row.get("email"):
                out[d] = {"name": (row.get("name") or "").strip(), "title": (row.get("title") or "").strip(),
                          "email": row["email"].strip(), "linkedin": (row.get("linkedin") or "").strip(),
                          "role": classify(row.get("title") or "") or "override", "source": "contacts.csv", "domain": d,
                          "confidence": None}
    return out


def pick_from_hunter(emails: List[dict], headcount: Optional[int], domain: str) -> Optional[dict]:
    cands = []
    for e in emails:
        role = classify(e.get("position") or "")
        if role and e.get("email"):
            cands.append((role, e))
    for want in role_order(headcount):
        group = [e for r, e in cands if r == want]
        if group:
            group.sort(key=lambda e: -(e.get("confidence") or 0))
            return _person(group[0], want, domain, "hunter.domain_search")
    return None


class PeopleOut(BaseModel):
    names: List[str]
    titles: List[str]


def grounded_fallback(llm, hunter: Hunter, domain: str, company: str, order: List[str]) -> dict:
    """Named founders/CTO via grounded search; the name must appear in the search text. Then Hunter Email Finder."""
    try:
        text, urls = llm.search("Who are the founders, CEO and CTO of %s (%s)? Give full names and titles." % (company, domain))
    except Exception as e:  # noqa: BLE001  grounding unavailable (quota/plan): no fallback, never a guess
        return {"unreachable_names": [], "sources": [], "note": "grounded search unavailable: %s" % type(e).__name__}
    out = llm.json("From this text list ONLY people explicitly named as founder, CEO or CTO of %s. "
                   "Return names[] (full names) and titles[] (same order). If none, empty lists.\n\nTEXT:\n%s" % (company, text), PeopleOut)
    found = []
    for n, t in zip(out["names"], out["titles"]):
        parts = n.strip().split()
        if len(parts) >= 2 and n.lower() in text.lower():  # a name must appear in the search text
            found.append({"name": n.strip(), "title": t})
    for want in order or ["founder", "cto"]:
        for p in found:
            if classify(p["title"]) != want:
                continue
            parts = p["name"].split()
            got = hunter.email_finder(domain, parts[0], parts[-1])
            if got:
                return {**_person({**got, "position": p["title"]}, want, domain, "grounded+hunter.email_finder"),
                        "name": p["name"], "title": p["title"], "sources": urls[:3]}
    return {"unreachable_names": found, "sources": urls[:3]}


def find_contact(llm, hunter: Hunter, domain: str, company: str, headcount: Optional[int],
                 overrides: Dict[str, dict]) -> dict:
    order = role_order(headcount)
    if domain in overrides:
        return {"person": overrides[domain], "order": order, "note": "contacts.csv override"}
    p = pick_from_hunter(hunter.domain_search(domain), headcount, domain)
    if p:
        return {"person": p, "order": order, "note": "Hunter titled match"}
    fb = grounded_fallback(llm, hunter, domain, company, order)
    if fb.get("email"):
        return {"person": fb, "order": order, "note": "grounded search + Email Finder"}
    return {"person": None, "order": order, "note": "no titled decision-maker and no findable email", "fallback": fb}
