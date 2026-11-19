"""Stage 1: find recently funded companies from Google News RSS. Regex gates and ranking, no LLM."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import httpx
import yaml
from lxml import etree

from .config import ROOT
from .db import connect, now
from .resolve import resolve

FEED = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
VERB = r"(?:raises|raised|secures|secured|closes|closed|lands|landed|bags|nabs|announces|snags|banks|gets|receives|completes|scores|brings in|unveils)"
HEAD = re.compile(r"^(?P<company>[A-Z0-9][^,:;|]{1,60}?)\s+%s\b" % VERB, re.I)
AMOUNT = re.compile(r"\$\s?(?P<n>\d+(?:\.\d+)?)\s?(?P<u>million|billion|m|b|mn|bn)\b", re.I)
ROUND = re.compile(r"\b(pre-?seed|seed|series\s+[a-c])\b", re.I)


def load_cfg(path=None) -> dict:
    return yaml.safe_load((path or ROOT / "config" / "discovery.yaml").read_text())


def parse_feed(xml: bytes) -> List[dict]:
    """Untrusted XML: no entity resolution, no network."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    root = etree.fromstring(xml, parser)
    out = []
    for it in root.iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(), "url": (it.findtext("link") or "").strip(),
                    "pub": (it.findtext("pubDate") or "").strip()})
    return out


def parse_headline(title: str) -> Optional[dict]:
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()  # drop " - Publisher"
    m = HEAD.match(t)
    if not m:
        return None
    a, r = AMOUNT.search(t), ROUND.search(t)
    amt = None
    if a:
        n = float(a.group("n"))
        amt = n * 1000 if a.group("u").lower() in ("billion", "b", "bn") else n
    rnd = re.sub(r"\s+", " ", r.group(1).lower()).replace("preseed", "pre-seed") if r else None
    return {"company": m.group("company").strip(), "amount_musd": amt, "round": rnd, "headline": t}


def gate(c: dict, pub: Optional[datetime], cfg: dict, today: datetime) -> Optional[str]:
    """Returns a drop reason, or None if the candidate passes."""
    low = c["headline"].lower()
    for w in cfg["exclude_words"]:
        if re.search(r"\b%s\b" % re.escape(w), low):
            return "excluded word: %s" % w
    if not c["round"] or c["round"] not in cfg["rounds_allowed"]:
        return "round not in scope"
    amt = c["amount_musd"]
    if amt is None or not (cfg["amount_musd"]["min"] <= amt <= cfg["amount_musd"]["max"]):
        return "amount outside band"
    if pub is None or (today - pub).days > cfg["max_age_days"] or pub > today + timedelta(days=1):
        return "too old or undated"
    return None


def rank(c: dict, pub: datetime, cfg: dict, today: datetime) -> float:
    age = max(0, (today - pub).days)
    fit = {"pre-seed": 20, "seed": 30, "series a": 30, "series b": 25, "series c": 15}.get(c["round"], 0)
    amt = c["amount_musd"]
    band = 20 if 5 <= amt <= 40 else 10
    return round((1 - age / cfg["max_age_days"]) * 40 + fit + band, 1)


def collect(client: httpx.Client, cfg: dict, today: Optional[datetime] = None) -> Dict[str, dict]:
    today = today or datetime.now(timezone.utc)
    found: Dict[str, dict] = {}
    for q in cfg["queries"]:
        try:
            r = client.get(FEED % quote_plus(q), timeout=15)
            r.raise_for_status()
            items = parse_feed(r.content)
        except (httpx.HTTPError, etree.XMLSyntaxError):
            continue
        for it in items:
            c = parse_headline(it["title"])
            if not c:
                continue
            try:
                pub = parsedate_to_datetime(it["pub"])
                pub = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pub = None
            if gate(c, pub, cfg, today):
                continue
            c.update(url=it["url"], published=pub.date().isoformat(), score=rank(c, pub, cfg, today))
            key = re.sub(r"[^a-z0-9]", "", c["company"].lower())
            if key not in found or found[key]["score"] < c["score"]:
                found[key] = c
    return found


def discover(client: httpx.Client, db, limit: Optional[int] = None, cfg: Optional[dict] = None,
             today: Optional[datetime] = None) -> List[dict]:
    """Find, dedupe against the cooldown, resolve domains. Returns candidates (domain None = flagged for a human)."""
    cfg = cfg or load_cfg()
    today = today or datetime.now(timezone.utc)
    limit = limit or cfg["max_candidates"]
    cutoff = (today - timedelta(days=cfg["cooldown_days"])).isoformat()
    ranked = sorted(collect(client, cfg, today).values(), key=lambda c: -c["score"])
    out: List[dict] = []
    with connect(db) as conn:
        recent = {r["company"].lower() for r in conn.execute("SELECT company FROM candidates WHERE found_at >= ?", (cutoff,))}
    for c in ranked:
        if len(out) >= limit:
            break
        if c["company"].lower() in recent:
            continue
        domain, note = resolve(client, c["company"], c["headline"])
        c = {**c, "domain": domain, "note": note}
        out.append(c)
        with connect(db) as conn:
            if domain:
                conn.execute("INSERT OR REPLACE INTO candidates(domain,company,headline,url,round,amount_musd,published,score,status,found_at) "
                             "VALUES(?,?,?,?,?,?,?,?, 'queued', ?)", (domain, c["company"], c["headline"], c["url"], c["round"], c["amount_musd"], c["published"], c["score"], now()))
            else:  # flagged rows keep a synthetic key so the cooldown still applies
                conn.execute("INSERT OR REPLACE INTO candidates(domain,company,headline,url,round,amount_musd,published,score,status,flag_reason,found_at) "
                             "VALUES(?,?,?,?,?,?,?,?, 'flagged', ?, ?)", ("?" + re.sub(r"[^a-z0-9]", "", c["company"].lower()), c["company"], c["headline"], c["url"], c["round"], c["amount_musd"], c["published"], c["score"], note, now()))
    return out


def list_flagged(db) -> List[dict]:
    with connect(db) as c:
        return [dict(r) for r in c.execute("SELECT domain AS key, company, headline, url, round, flag_reason FROM candidates WHERE status='flagged' ORDER BY found_at DESC")]


def resolve_flagged(db, key: str, domain: str) -> str:
    """A human supplies the domain for a flagged lead; it becomes a normal queued candidate."""
    from .config import clean_domain, valid_domain
    d = clean_domain(domain)
    if not valid_domain(d):
        raise ValueError("not a valid domain")
    with connect(db) as c:
        row = c.execute("SELECT * FROM candidates WHERE domain=? AND status='flagged'", (key,)).fetchone()
        if not row:
            raise LookupError("no such flagged lead")
        c.execute("DELETE FROM candidates WHERE domain=?", (key,))
        c.execute("INSERT OR REPLACE INTO candidates(domain,company,headline,url,round,amount_musd,published,score,status,found_at) VALUES(?,?,?,?,?,?,?,?, 'queued', ?)",
                  (d, row["company"], row["headline"], row["url"], row["round"], row["amount_musd"], row["published"], row["score"], now()))
    return d
