"""Step 4: agent loop. While the qualify line sits inside [low, high], research one more thing."""
from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Optional

import httpx
from pydantic import BaseModel

from .extract import Ledger, ExtractOut, build_prompt as extract_prompt
from .qualify import qualify
from .scrape import Outcome, Page, fetch

ALLOWED_PATHS = ["/", "/pricing", "/security", "/trust", "/customers", "/about", "/careers", "/enterprise",
                 "/blog", "/docs", "/integrations", "/solutions", "/compliance", "/contact"]
BUDGET = {"tool_calls": 3, "searches": 2, "seconds": 120}
TOOLS = ("fetch_page", "web_research", "job_postings")


class ToolChoice(BaseModel):
    tool: str  # fetch_page | web_research | job_postings
    argument: str  # path | search query | company slug
    reason: str


def uncertain(res: dict, line: int) -> bool:
    return res["low"] < line <= res["high"]


def choose_tool(llm, domain: str, res: dict, history: List[dict], icp: dict) -> dict:
    unk = [s["signal"] + (" [external]" if s["external"] else "") for s in res["signals"] if s["status"] == "unknown"]
    prompt = (
        "You are a sales researcher deciding the ONE most useful next lookup for %s.\n"
        "Score so far: %d to %d (qualify line %d). Unknown signals: %s.\n"
        "Tools: fetch_page(argument = one of %s), web_research(argument = a focused Google query), "
        "job_postings(argument = the company's likely job-board slug, e.g. 'acme').\n"
        "Already tried (do not repeat): %s\nPick the single call most likely to settle an unknown signal."
    ) % (domain, res["low"], res["high"], icp["thresholds"]["qualify"], ", ".join(unk) or "none",
         ", ".join(ALLOWED_PATHS), [(h["tool"], h["argument"]) for h in history] or "nothing")
    return llm.json(prompt, ToolChoice)


def job_postings(client: httpx.Client, slug: str) -> Optional[str]:
    """Greenhouse / Lever / Ashby public APIs. Returns a text list of titles, or None if no board found."""
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    if not slug:
        return None
    tries = [
        ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug, lambda j: [x.get("title", "") for x in j.get("jobs", [])]),
        ("lever", "https://api.lever.co/v0/postings/%s?mode=json" % slug, lambda j: [x.get("text", "") for x in j] if isinstance(j, list) else []),
        ("ashby", "https://api.ashbyhq.com/posting-api/job-board/%s" % slug, lambda j: [x.get("title", "") for x in j.get("jobs", [])]),
    ]
    for name, url, titles in tries:
        try:
            r = client.get(url, timeout=10)
            if r.status_code != 200:
                continue
            ts = [t for t in titles(r.json()) if t]
            return "Open roles on %s job board for %s (%d): %s" % (name, slug, len(ts), "; ".join(ts[:60]) or "none")
        except (httpx.HTTPError, ValueError):
            continue
    return None


def run_agent(llm, client: httpx.Client, domain: str, icp: dict, profile: dict, ledger: Ledger,
              pages: Dict[str, Page], res: dict, budget: Optional[dict] = None,
              clock: Callable[[], float] = time.monotonic) -> dict:
    b = {**BUDGET, **(budget or {})}
    line = icp["thresholds"]["qualify"]
    start = clock()
    steps: List[dict] = []
    calls = searches = 0
    while uncertain(res, line):
        stop = None
        if calls >= b["tool_calls"]:
            stop = "tool budget used"
        elif clock() - start >= b["seconds"]:
            stop = "time budget used"
        if stop:
            steps.append({"stopped": stop})
            break
        try:
            ch = choose_tool(llm, domain, res, steps, icp)
        except Exception as e:  # noqa: BLE001
            steps.append({"stopped": "planner failed: %s" % type(e).__name__})
            break
        tool, arg = ch["tool"], ch["argument"].strip()
        if tool == "fetch_page" and not arg.startswith("/"):
            arg = "/" + arg
        step = {"tool": tool, "argument": arg, "reason": ch["reason"], "before": [res["low"], res["high"]]}
        if tool not in TOOLS:
            step["error"] = "unknown tool"
        elif any(h.get("tool") == tool and h.get("argument") == arg for h in steps):
            step["error"] = "repeat refused"
        elif tool == "fetch_page" and arg not in ALLOWED_PATHS:
            step["error"] = "path not allow-listed"
        elif tool == "web_research" and searches >= b["searches"]:
            step["error"] = "search budget used"
        if "error" in step:
            calls += 1  # a refused call still burns budget, so a confused planner cannot loop
            steps.append(step)
            continue
        calls += 1
        new_text, label = "", ""
        try:
            if tool == "fetch_page":
                pg = fetch(client, "https://" + domain, arg)
                pages[arg] = pg
                step["outcome"] = pg.outcome.value
                new_text, label = (pg.text, pg.url) if pg.outcome == Outcome.OK else ("", "")
            elif tool == "web_research":
                searches += 1
                text, urls = llm.search(arg)
                step["sources"] = urls[:5]
                new_text, label = text, "web_research:%s" % arg
            else:
                t = job_postings(client, arg)
                step["outcome"] = "OK" if t else "NOT_FOUND"
                new_text, label = (t or ""), "job_board:%s" % arg
        except Exception as e:  # noqa: BLE001
            step["error"] = type(e).__name__
        added = 0
        if new_text and label:
            try:
                out = llm.json(extract_prompt(domain, {label: new_text}), ExtractOut)
                added = ledger.add(out["facts"], {label: new_text}, source=tool)
                if not profile.get("headcount") and out["profile"].get("headcount"):
                    profile["headcount"] = out["profile"]["headcount"]
            except Exception as e:  # noqa: BLE001
                step["error"] = type(e).__name__
        step["new_evidence"] = added
        res = qualify(llm, icp, profile, ledger, pages)
        step["after"] = [res["low"], res["high"]]
        steps.append(step)
    return {"result": res, "steps": steps, "tool_calls": calls, "searches": searches,
            "seconds": round(clock() - start, 1)}
