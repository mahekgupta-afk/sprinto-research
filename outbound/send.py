"""Step 9: send. There is deliberately NO recipient parameter: mail only ever goes to TO_EMAIL."""
from __future__ import annotations

from urllib.parse import quote

import httpx

from .config import Settings

RESEND = "https://api.resend.com/emails"


def compose_body(body: str, intended_for: str, sender_name: str) -> str:
    return "%s\n\n%s\n\n--\nIntended recipient: %s" % (body.strip(), sender_name, intended_for)


def send_email(subject: str, body: str, intended_for: str, *, settings: Settings, client: httpx.Client) -> dict:
    payload = {"from": "%s <%s>" % (settings.sender_name, settings.from_email), "to": [settings.to_email],
               "subject": subject, "text": compose_body(body, intended_for, settings.sender_name)}
    r = client.post(RESEND, json=payload, headers={"Authorization": "Bearer " + settings.resend_api_key}, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError("resend returned HTTP %d" % r.status_code)
    return {"id": r.json().get("id"), "to": settings.to_email}


def gmail_link(settings: Settings, subject: str, body: str, intended_for: str) -> str:
    return "https://mail.google.com/mail/?view=cm&fs=1&to=%s&su=%s&body=%s" % (
        quote(settings.to_email), quote(subject), quote(compose_body(body, intended_for, settings.sender_name)))
