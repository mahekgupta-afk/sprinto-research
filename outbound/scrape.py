"""Step 1: scrape with typed outcomes. Anything but OK is UNKNOWN, never evidence."""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

PATHS = ["/", "/pricing", "/security", "/trust", "/customers", "/about", "/careers"]
MAX_BYTES = 2_000_000
MIN_TEXT = 200
UA = "Mozilla/5.0 (compatible; OutboundAutopilotResearch/1.0)"


class Outcome(str, Enum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    EMPTY_SHELL = "EMPTY_SHELL"
    NON_HTML = "NON_HTML"
    TOO_BIG = "TOO_BIG"


@dataclass
class Page:
    path: str
    url: str
    outcome: Outcome
    status: int = 0
    text: str = ""
    hash: str = ""
    final_url: str = ""
    title: str = ""

    def trace(self) -> dict:
        return {"path": self.path, "url": self.url, "outcome": self.outcome.value,
                "status": self.status, "chars": len(self.text), "final_url": self.final_url}


def html_to_text(html: str):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg", "template"]):
        t.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return title, text


def text_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"[^a-z]+", "", text.lower()).encode()).hexdigest()


def fetch(client: httpx.Client, base: str, path: str) -> Page:
    url = base + path
    try:
        r = client.get(url, follow_redirects=True)
    except httpx.TimeoutException:
        return Page(path, url, Outcome.TIMEOUT)
    except httpx.HTTPError:
        return Page(path, url, Outcome.BLOCKED)
    final = str(r.url)
    if r.status_code == 404 or r.status_code == 410:
        return Page(path, url, Outcome.NOT_FOUND, r.status_code, final_url=final)
    if r.status_code in (401, 403, 429, 451, 503) or r.status_code >= 500:
        return Page(path, url, Outcome.BLOCKED, r.status_code, final_url=final)
    if r.status_code >= 400:
        return Page(path, url, Outcome.NOT_FOUND, r.status_code, final_url=final)
    ctype = r.headers.get("content-type", "").lower()
    if "html" not in ctype and ctype:
        return Page(path, url, Outcome.NON_HTML, r.status_code, final_url=final)
    if len(r.content) > MAX_BYTES:
        return Page(path, url, Outcome.TOO_BIG, r.status_code, final_url=final)
    title, text = html_to_text(r.text)
    if len(text) < MIN_TEXT:
        return Page(path, url, Outcome.EMPTY_SHELL, r.status_code, final_url=final, title=title)
    return Page(path, url, Outcome.OK, r.status_code, text, text_hash(text), final, title)


def scrape_site(client: httpx.Client, domain: str, paths: List[str] = None) -> Dict[str, Page]:
    """Fetch the page set. A probe path catches sites that return 200 for everything (soft 404)."""
    base = "https://" + domain
    probe = fetch(client, base, "/__probe-%s" % uuid.uuid4().hex[:10])
    soft_hash = probe.hash if probe.outcome == Outcome.OK else None
    out: Dict[str, Page] = {}
    home_hash = None
    for p in (paths or PATHS):
        pg = fetch(client, base, p)
        if pg.outcome == Outcome.OK:
            if soft_hash and pg.hash == soft_hash and p != "/":
                pg = Page(p, pg.url, Outcome.NOT_FOUND, pg.status, final_url=pg.final_url)
            elif p == "/":
                home_hash = pg.hash
            elif home_hash and pg.hash == home_hash:  # redirected back to home
                pg = Page(p, pg.url, Outcome.NOT_FOUND, pg.status, final_url=pg.final_url)
        out[p] = pg
    return out


def make_client() -> httpx.Client:
    return httpx.Client(timeout=12.0, headers={"User-Agent": UA, "Accept": "text/html"}, follow_redirects=True)
