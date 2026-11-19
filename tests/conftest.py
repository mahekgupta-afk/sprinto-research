import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outbound.config import Settings, load_icp, load_proof_lines  # noqa: E402


class FakeLLM:
    """Scripted LLM. handlers: {SchemaName: callable(prompt) -> dict | list of dicts (consumed in order)}."""

    def __init__(self, handlers=None, search_text="", search_urls=None):
        self.h = handlers or {}
        self.search_text, self.search_urls = search_text, search_urls or []
        self.prompts, self.searches, self.calls = [], [], 0

    def json(self, prompt, schema, strong=False):
        self.calls += 1
        name = schema.__name__
        self.prompts.append((name, prompt))
        h = self.h[name]
        out = h(prompt) if callable(h) else (h.pop(0) if isinstance(h, list) and len(h) > 1 else (h[0] if isinstance(h, list) else h))
        return schema.model_validate(out).model_dump()

    def search(self, q):
        self.searches.append(q)
        return self.search_text, self.search_urls


@pytest.fixture
def settings(tmp_path):
    return Settings(gemini_api_key="AIzaFAKEFAKEFAKEFAKEFAKEFAKE1234", resend_api_key="re_FAKEFAKEFAKEFAKE1234",
                    hunter_api_key="a" * 40, to_email="me@example.com", sender_name="Sam",
                    out_dir=tmp_path / "out", cache_dir=tmp_path / "cache", require_approval=False)


@pytest.fixture
def icp():
    return load_icp()


@pytest.fixture
def proofs():
    return load_proof_lines()


LONG = "We help teams ship secure software every day with a fast reliable platform. " * 6


def html(text=LONG, title="t"):
    return "<html><head><title>%s</title></head><body><p>%s</p><script>var x=1</script></body></html>" % (title, text)
