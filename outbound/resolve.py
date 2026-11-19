"""Turn a company name from a headline into a domain, accepted only if the homepage really matches."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

import httpx

from .extract import norm
from .scrape import Outcome, fetch

TLDS = ["com", "io", "ai", "co", "app", "dev"]
STOP = set("raises raised secures closes funding round series seed million the and for with from that startup company platform software announces".split())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def topic_words(headline: str, company: str) -> List[str]:
    cw = set(re.findall(r"[a-z]+", company.lower()))
    return [w for w in re.findall(r"[a-z]{5,}", headline.lower()) if w not in STOP and w not in cw]


def resolve(client: httpx.Client, company: str, headline: str) -> Tuple[Optional[str], str]:
    """Returns (domain, note). domain None means flagged for a human, with the reason in note."""
    s = slug(company)
    if len(s) < 3:
        return None, "company name too short to resolve"
    topics = topic_words(headline, company)
    seen_unreadable = False
    for tld in TLDS:
        d = "%s.%s" % (s, tld)
        pg = fetch(client, "https://" + d, "/")
        if pg.outcome != Outcome.OK:
            seen_unreadable = seen_unreadable or pg.outcome in (Outcome.BLOCKED, Outcome.TIMEOUT)
            continue
        text = norm(pg.title + " " + pg.text)
        if company.lower() in text or s in re.sub(r"[^a-z0-9]", "", text):
            if not topics or any(t in text for t in topics):
                return d, "homepage names the company and matches the headline topic"
            return None, "%s names the company but no headline topic word: check by hand" % d
    return None, "no homepage matched" + (" (some sites unreadable)" if seen_unreadable else "")
