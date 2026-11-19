"""Step 6: two pain points for this persona, each citing evidence."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel

from .extract import Ledger


class Pain(BaseModel):
    pain: str
    evidence_ids: List[str]
    data_handled: str
    buyer: str


class PainsOut(BaseModel):
    pains: List[Pain]


PERSONA = {"security": "a security/GRC lead who owns audits and customer questionnaires",
           "cto": "a CTO who loses engineering time to audit evidence and security reviews",
           "founder": "a founder who sees enterprise deals stall on security questions",
           "override": "a senior decision-maker"}


def pains(llm, profile: dict, person: dict, ledger: Ledger) -> List[dict]:
    ev = "\n".join('%s: %s | "%s"' % (e["id"], e["claim"], e["quote"]) for e in ledger.items)
    prompt = (
        "Company: %s - %s.\nPersona: %s.\nEvidence ledger:\n%s\n\n"
        "Write exactly 2 compliance-related pain points this persona likely has. Each must: cite 1+ evidence IDs from the ledger, "
        "name the specific data their product handles (data_handled) and who their buyer is (buyer). "
        "Never claim anything the evidence does not support." % (
            profile.get("name"), profile.get("one_liner"), PERSONA.get(person.get("role"), PERSONA["override"]), ev))
    out = llm.json(prompt, PainsOut)["pains"][:2]
    valid = ledger.ids()
    return [p for p in out if any(e in valid for e in p["evidence_ids"])]
