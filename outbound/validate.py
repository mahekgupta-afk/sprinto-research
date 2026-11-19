"""Step 8a: deterministic email validator. Every rule is code, none is an LLM opinion."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Dict, List, Optional

from .extract import norm

MAX_WORDS = 110
FRAMEWORKS = ["soc 2", "iso 27001", "gdpr", "hipaa", "pci", "nist", "iso 42001", "fedramp", "iso 27701", "ccpa"]
HEDGES = ["maybe", "perhaps", "might", "possibly", "probably", "seems", "likely", "somewhat", "sort of", "kind of",
          "i guess", "i think", "i believe"]
BANNED = ["your website", "your site", "your web page", "endpoint", "404", "not_found", "scrape", "scraped", "crawl",
          "i noticed that your", "i hope this", "hope you're well", "touch base", "synergy", "game-changer", "game changer",
          "revolutionize", "cutting-edge", "circle back", "reach out", "quick question", "just checking",
          "per my last", "as an ai", "we scanned", "our research bot"]
SPELLED = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
                     r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
                     r"thousand|million|billion|dozen)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|dear|good (morning|afternoon|evening)|greetings)\b", re.I)
MARKDOWN = re.compile(r"(\*|`|#|^\s*[-•]\s|\]\(|^\s*\d+\.\s|_{2})", re.M)
PLACEHOLDER = re.compile(r"(\[[^\]]*\]|\{\{|\}\}|<[^>]+>|\bXYZ\b|\bTODO\b|lorem ipsum|\bCOMPANY\b|\bNAME\b)")
STOP = set("with that this from your their they them have into over more most also been will would about which "
           "where there these those than then what when who whom for and the are our out can use used using "
           "help helps built make makes software platform company business teams team".split())
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def words(s: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", s))


def sentences(s: str) -> List[str]:
    return [x for x in re.split(r"(?<=[.?!])\s+", s.strip()) if x]


def _numbers(text: str) -> set:
    t = text.lower()
    for fw in ("soc 2", "iso 27001", "iso 27701", "iso 42001", "type ii", "type 2", "type i", "pci dss 4.0"):
        t = t.replace(fw, " ")
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(t)}


def terms(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]{5,}", (text or "").lower()) if w not in STOP]


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    return None


def validate(subject: str, body: str, ctx: Dict, today: Optional[date] = None) -> List[str]:
    """ctx: company, first_name, profile, evidence (list), proof_lines, hook_evidence_id, proof_line."""
    today = today or date.today()
    fails: List[str] = []
    low = body.lower()
    ev = ctx["evidence"]
    if words(body) > MAX_WORDS:
        fails.append("over %d words (%d)" % (MAX_WORDS, words(body)))
    if body.count("?") != 1:
        fails.append("must contain exactly one question mark (has %d)" % body.count("?"))
    if "!" in body or "!" in subject:
        fails.append("no exclamation marks")
    if MARKDOWN.search(body):
        fails.append("no markdown")
    if PLACEHOLDER.search(body) or PLACEHOLDER.search(subject):
        fails.append("placeholder text left in")
    if GREETING.search(body):
        fails.append("no greeting line")
    sents = sentences(body)
    if not sents:
        return fails + ["empty body"]
    prof = ctx["profile"]
    pterms = set(terms("%s %s %s" % (prof.get("one_liner", ""), prof.get("product_type", ""), prof.get("name", ""))))
    if not any(t in sents[0].lower() for t in pterms):
        fails.append("first sentence must use a term from their product")
    company = (prof.get("name") or ctx["company"]).lower()
    hook = next((e for e in ev if e["id"] == ctx.get("hook_evidence_id")), None)
    if hook is None:
        fails.append("hook_evidence_id does not point to real evidence")
    else:
        if re.search(r"\bGET /|NOT_FOUND|\b404\b|BLOCKED|TIMEOUT", hook["quote"] + hook["claim"]):
            fails.append("hook is a fetch log line, not evidence")
    hookterms = set(terms(hook["claim"] + " " + hook["quote"])) if hook else set()
    sl = subject.lower()
    if company not in sl and ctx["company"].lower() not in sl:
        fails.append("subject must contain the company name")
    elif not any(t in sl for t in (hookterms | pterms)):
        fails.append("subject needs a hook or product word")
    if hook and not any(t in low for t in hookterms):
        fails.append("body does not use the hook")
    if ctx.get("first_name") and ctx["first_name"].lower() not in low:
        fails.append("must address the person by first name")
    allowed = set()
    for e in ev:
        allowed |= _numbers(e["quote"] + " " + e["claim"])
    for p in ctx["proof_lines"]:
        allowed |= _numbers(p)
    allowed |= {str(prof["headcount"])} if prof.get("headcount") else set()
    bad = sorted(n for n in _numbers(body + " " + subject) if n not in allowed)
    if bad:
        fails.append("numbers not in evidence: %s" % ", ".join(bad))
    if SPELLED.search(body):
        fails.append("spelled-out numbers not allowed")
    hedges = sum(len(re.findall(r"\b%s\b" % re.escape(h), low)) for h in HEDGES)
    if hedges > 1:
        fails.append("more than one hedge word")
    if sum(1 for f in FRAMEWORKS if f in low) >= 3:
        fails.append("lists 3+ frameworks")
    for b in BANNED:
        if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(b), low) or b in subject.lower():
            fails.append("banned phrase: %s" % b)
    if re.search(r"\brecent(ly)?\b|\bjust raised\b", low):
        ok = False
        for e in ev:
            d = _parse_date(e.get("date"))
            if e["topic"] == "funding" and d and 0 <= (today - d).days <= 183:
                ok = True
        if not ok:
            fails.append("'recent' needs funding evidence dated within 6 months")
    mentions = [s for s in sents if "sprinto" in s.lower()]
    proof = ctx.get("proof_line") or ""
    if proof not in ctx["proof_lines"]:
        fails.append("proof line is not from sprinto_facts.md")
    elif norm(proof) not in norm(body):
        fails.append("proof line missing from body")
    for s in mentions:
        if norm(proof) not in norm(s):
            fails.append("claim about Sprinto outside the proof whitelist")
            break
    return fails
