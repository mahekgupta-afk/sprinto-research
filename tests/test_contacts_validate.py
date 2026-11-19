import json
from datetime import date

import httpx
import respx

from conftest import FakeLLM
from outbound.contacts import Hunter, classify, find_contact, pick_from_hunter, read_overrides, role_order
from outbound.validate import validate

# ---------- contacts ----------
def test_role_rules_by_headcount():
    assert role_order(30) == ["founder", "cto"]
    assert role_order(50) == ["founder", "cto"]
    assert role_order(120) == ["security", "cto", "founder"]
    assert role_order(None) == ["security", "cto", "founder"]
    assert role_order(500) == ["security", "cto"]


def test_drops_sales_marketing_hr_titles():
    for t in ["VP Sales", "Head of Marketing", "HR Manager", "Talent Acquisition Lead", "Customer Success Director", "Growth Lead"]:
        assert classify(t) is None
    assert classify("Head of Security & Compliance") == "security"
    assert classify("Co-Founder & CEO") == "founder" and classify("CTO") == "cto"


EMAILS = [{"email": "s@a.com", "first_name": "S", "last_name": "Sales", "position": "VP Sales", "confidence": 99},
          {"email": "c@a.com", "first_name": "Cy", "last_name": "Tech", "position": "CTO", "confidence": 90},
          {"email": "f@a.com", "first_name": "Fay", "last_name": "Founder", "position": "Founder", "confidence": 80},
          {"email": "g@a.com", "first_name": "Gia", "last_name": "Grc", "position": "Head of GRC", "confidence": 70}]


def test_pick_follows_headcount_rules():
    assert pick_from_hunter(EMAILS, 30, "a.com")["email"] == "f@a.com"
    assert pick_from_hunter(EMAILS, 120, "a.com")["email"] == "g@a.com"
    assert pick_from_hunter(EMAILS[:2], 500, "a.com")["email"] == "c@a.com"
    assert pick_from_hunter(EMAILS[:1], 120, "a.com") is None


@respx.mock
def test_hunter_responses_are_cached(settings):
    route = respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": EMAILS}})
    h = Hunter(settings, httpx.Client())
    assert len(h.domain_search("a.com")) == 4
    assert len(h.domain_search("a.com")) == 4
    assert route.call_count == 1 and h.live_calls == 1
    cached = "".join(p.read_text() for p in (settings.cache_dir / "hunter").iterdir())
    assert settings.hunter_api_key not in cached
    h2 = Hunter(settings, httpx.Client())  # new process, same cache
    h2.domain_search("a.com")
    assert route.call_count == 1


@respx.mock
def test_fallback_grounded_name_then_email_finder(settings):
    respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": []}})
    respx.get("https://api.hunter.io/v2/email-finder").respond(200, json={"data": {"email": "ada@a.com", "first_name": "Ada", "last_name": "Lovelace", "confidence": 88}})
    llm = FakeLLM({"PeopleOut": {"names": ["Ada Lovelace"], "titles": ["Founder and CEO"]}}, search_text="Acme was founded by Ada Lovelace, CEO.")
    r = find_contact(llm, Hunter(settings, httpx.Client()), "a.com", "Acme", 20, {})
    assert r["person"]["email"] == "ada@a.com" and r["person"]["name"] == "Ada Lovelace" and "grounded" in r["person"]["source"]


@respx.mock
def test_fallback_never_invents_a_name(settings):
    respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": []}})
    finder = respx.get("https://api.hunter.io/v2/email-finder").respond(200, json={"data": {"email": "x@a.com"}})
    llm = FakeLLM({"PeopleOut": {"names": ["Made Up"], "titles": ["Founder"]}}, search_text="Acme is a company with no named leaders.")
    r = find_contact(llm, Hunter(settings, httpx.Client()), "a.com", "Acme", 20, {})
    assert r["person"] is None and finder.call_count == 0


@respx.mock
def test_name_found_but_no_address_is_no_contact(settings):
    respx.get("https://api.hunter.io/v2/domain-search").respond(200, json={"data": {"emails": []}})
    respx.get("https://api.hunter.io/v2/email-finder").respond(200, json={"data": {"email": None}})
    llm = FakeLLM({"PeopleOut": {"names": ["Ada Lovelace"], "titles": ["Founder"]}}, search_text="Ada Lovelace founded Acme.")
    assert find_contact(llm, Hunter(settings, httpx.Client()), "a.com", "Acme", 20, {})["person"] is None


def test_contacts_csv_overrides_hunter(settings, tmp_path):
    f = tmp_path / "contacts.csv"
    f.write_text("domain,name,title,email\na.com,Zed Zee,CTO,zed@a.com\n")
    ov = read_overrides(f)
    r = find_contact(FakeLLM(), Hunter(settings, httpx.Client()), "a.com", "Acme", 20, ov)
    assert r["person"]["email"] == "zed@a.com" and r["person"]["source"] == "contacts.csv"


# ---------- validator ----------
EV = [{"id": "E1", "topic": "customers", "claim": "serves hospitals in 12 states", "quote": "We process payroll for hospitals across 12 states", "url": "u", "date": None},
      {"id": "E2", "topic": "funding", "claim": "raised seed", "quote": "Acme raised a seed round", "url": "u", "date": "2026-09-01"}]
PROOF = ["Sprinto automates evidence collection for SOC 2 and ISO 27001 by connecting to cloud, HR and engineering tools."]
PROFILE = {"name": "Acme", "one_liner": "payroll software for hospitals", "product_type": "software", "headcount": 40}
CTX = {"company": "Acme", "first_name": "Priya", "profile": PROFILE, "evidence": EV, "proof_lines": PROOF,
       "hook_evidence_id": "E1", "proof_line": PROOF[0]}
SUBJ = "Acme payroll and hospital buyers"
GOOD = ("Priya, running payroll for hospitals across 12 states means every health system buyer sends you a security questionnaire. "
        + PROOF[0] + " Would a faster route to a SOC 2 report help your next hospital deal?")
TODAY = date(2026, 11, 17)


def fails(body=GOOD, subject=SUBJ, **ctx):
    return validate(subject, body, {**CTX, **ctx}, TODAY)


def has(fs, needle):
    return any(needle in f for f in fs)


def test_good_email_passes():
    assert fails() == []


def test_rule_word_limit_and_question_marks():
    assert has(fails(GOOD + " " + "word " * 80), "over 110")
    assert has(fails(GOOD.replace("?", ".")), "exactly one question")
    assert has(fails(GOOD + " Why?"), "exactly one question")


def test_rule_no_exclamation_markdown_placeholders_greeting():
    assert has(fails(GOOD.replace("deal?", "deal!?")), "exclamation")
    assert has(fails("**" + GOOD), "markdown")
    assert has(fails(GOOD + " [Name]"), "placeholder")
    assert has(fails("Hi Priya, " + GOOD), "greeting")


def test_rule_first_sentence_product_term_and_subject():
    bad = GOOD.replace("running payroll for hospitals across 12 states means", "being busy this quarter means")
    assert has(fails(bad), "first sentence")
    assert has(fails(subject="Quick note for you"), "company name")
    assert has(fails(subject="Acme"), "hook or product word")


def test_rule_numbers_must_be_in_evidence():
    assert has(fails(GOOD.replace("12 states", "70 states")), "numbers not in evidence")
    assert has(fails(GOOD.replace("12 states", "twelve states")), "spelled-out")


def test_rule_hedges_and_frameworks():
    assert has(fails(GOOD.replace("means", "might possibly mean")), "hedge")
    assert fails(GOOD.replace("means", "perhaps means")) == []  # a single hedge is allowed
    assert has(fails(GOOD.replace("your next hospital deal", "SOC 2, HIPAA and GDPR work")), "frameworks")


def test_rule_recent_needs_dated_funding():
    assert has(fails(GOOD.replace("Priya,", "Priya, after your recent growth,"), evidence=[EV[0]]), "recent")
    ev_old = [EV[0], {**EV[1], "date": "2025-01-01"}]
    assert has(fails(GOOD.replace("Priya,", "Priya, after your recent raise,"), evidence=ev_old), "recent")
    assert fails(GOOD.replace("Priya,", "Priya, after your recent raise,")) == []


def test_rule_banned_and_scrape_giveaways():
    for phrase in ["your website", "endpoint", "404", "touch base"]:
        assert has(fails(GOOD.replace("means", "means " + phrase + " says")), "banned"), phrase


def test_rule_hook_cannot_be_a_fetch_log():
    ev = [{**EV[0], "quote": "GET /security -> NOT_FOUND"}]
    assert has(fails(evidence=ev), "fetch log")
    assert has(fails(hook_evidence_id="E9"), "hook_evidence_id")


def test_rule_proof_line_whitelist():
    assert has(fails(proof_line="Sprinto is the best"), "not from sprinto_facts")
    assert has(fails(GOOD.replace(" Would", " Sprinto customers close deals twice as fast. Would")), "outside the proof")
    assert has(fails(GOOD.replace(PROOF[0], "")), "proof line missing")


def test_must_address_by_first_name():
    assert has(fails(GOOD.replace("Priya", "friend")), "first name")
