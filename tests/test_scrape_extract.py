import httpx
import respx

from conftest import LONG, html
from outbound.extract import Ledger, extract, quote_in_text
from outbound.scrape import Outcome, fetch, make_client, scrape_site


@respx.mock
def test_outcomes():
    respx.get("https://a.com/ok").respond(200, text=html(), headers={"content-type": "text/html"})
    respx.get("https://a.com/nf").respond(404)
    respx.get("https://a.com/blk").respond(403)
    respx.get("https://a.com/shell").respond(200, text="<html><body><div id=root></div></body></html>", headers={"content-type": "text/html"})
    respx.get("https://a.com/pdf").respond(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    respx.get("https://a.com/big").respond(200, content=b"x" * 2_100_000, headers={"content-type": "text/html"})
    respx.get("https://a.com/slow").mock(side_effect=httpx.ReadTimeout("t"))
    c = make_client()
    got = {p: fetch(c, "https://a.com", p).outcome for p in ["/ok", "/nf", "/blk", "/shell", "/pdf", "/big", "/slow"]}
    assert got == {"/ok": Outcome.OK, "/nf": Outcome.NOT_FOUND, "/blk": Outcome.BLOCKED, "/shell": Outcome.EMPTY_SHELL,
                   "/pdf": Outcome.NON_HTML, "/big": Outcome.TOO_BIG, "/slow": Outcome.TIMEOUT}


@respx.mock
def test_soft_404_detected_by_hash():
    # site answers 200 with the same body for any path, including the probe
    respx.get(url__regex=r"https://soft\.com/.*").respond(200, text=html("Sorry we cannot find that page anywhere on our site. " * 8), headers={"content-type": "text/html"})
    pages = scrape_site(make_client(), "soft.com", ["/pricing", "/security"])
    assert pages["/pricing"].outcome == Outcome.NOT_FOUND and pages["/security"].outcome == Outcome.NOT_FOUND


@respx.mock
def test_blocked_page_is_not_evidence():
    respx.get(url__regex=r"https://b\.com/.*").respond(403)
    pages = scrape_site(make_client(), "b.com", ["/", "/security"])
    assert all(p.outcome == Outcome.BLOCKED and p.text == "" for p in pages.values())


def test_quote_verification_normalises_and_rejects():
    text = "We’re SOC 2   Type II  certified and\nISO 27001 ready."
    assert quote_in_text("we're soc 2 type ii certified", text)
    assert not quote_in_text("we are HIPAA certified today", text)
    assert not quote_in_text("short", "short")  # too short to count


def test_extract_keeps_only_verified_facts():
    from outbound.scrape import Page
    page = Page("/", "https://a.com/", Outcome.OK, 200, "Acme builds payroll software for hospitals and clinics across the US. " * 4)
    facts = [{"topic": "product", "claim": "payroll for hospitals", "quote": "builds payroll software for hospitals", "url": "https://a.com/"},
             {"topic": "security", "claim": "has SOC 2", "quote": "We are SOC 2 Type II certified", "url": "https://a.com/"}]
    from conftest import FakeLLM
    llm = FakeLLM({"ExtractOut": {"facts": facts, "profile": {"name": "Acme", "one_liner": "payroll software", "product_type": "software", "headcount": 40}}})
    led = Ledger()
    prof = extract(llm, "a.com", {"/": page}, led)
    assert prof["name"] == "Acme"
    assert [e["id"] for e in led.items] == ["E1"] and led.items[0]["verified"]
    assert len(led.rejected) == 1


def test_extract_with_no_readable_pages_makes_no_llm_call():
    from conftest import FakeLLM
    from outbound.scrape import Page
    llm = FakeLLM({})
    assert extract(llm, "a.com", {"/": Page("/", "u", Outcome.BLOCKED)}, Ledger()) == {}
    assert llm.calls == 0
