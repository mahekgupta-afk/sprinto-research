#!/usr/bin/env python
"""Checks Hunter, Gemini structured output, Gemini grounding and sends ONE test email to TO_EMAIL."""
import sys

import httpx
from pydantic import BaseModel

from outbound.config import ConfigError, load_settings, require, scrub
from outbound.contacts import HUNTER
from outbound.llm import LLM
from outbound.send import RESEND


class Ping(BaseModel):
    ok: bool
    word: str


def check(name, fn, s):
    try:
        detail = fn()
        print("PASS  %-22s %s" % (name, detail))
        return True
    except Exception as e:  # noqa: BLE001
        print("FAIL  %-22s %s" % (name, scrub("%s: %s" % (type(e).__name__, e), s)))
        return False


def main():
    s = load_settings()
    try:
        require(s)
    except ConfigError as e:
        print(e)
        return 1
    http, llm = httpx.Client(timeout=20), LLM(s)

    def hunter():
        r = http.get(HUNTER + "/account", params={"api_key": s.hunter_api_key})
        r.raise_for_status()
        return "account reachable"

    def structured():
        out = llm.json("Return ok=true and word='ready'.", Ping)
        assert out["ok"] is True
        return "structured output ok (%s)" % s.model_fast

    def grounding():
        text, urls = llm.search("What does Sprinto (sprinto.com) sell? One sentence.")
        assert text.strip()
        return "%d chars, %d sources (%s)" % (len(text), len(urls), s.model_grounding)

    def mail():
        r = http.post(RESEND, headers={"Authorization": "Bearer " + s.resend_api_key},
                      json={"from": "%s <%s>" % (s.sender_name, s.from_email), "to": [s.to_email],
                            "subject": "Outbound Autopilot preflight", "text": "Preflight test. If you can read this, sending works."})
        r.raise_for_status()
        return "test email sent to TO_EMAIL"

    ok = [check("Hunter", hunter, s), check("Gemini structured", structured, s), check("Gemini grounding", grounding, s), check("Resend send", mail, s)]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
