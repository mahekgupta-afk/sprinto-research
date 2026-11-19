"""Gemini wrapper with call pacing. Everything LLM-shaped goes through this class."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, List, Optional, Tuple, Type

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings: Settings, client: Any = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.s = settings
        self._client = client
        self._sleep, self._clock = sleep, clock
        self._last = None  # type: Optional[float]
        self.calls = 0

    @property
    def client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.s.gemini_api_key)
        return self._client

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.s.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.calls += 1

    def json(self, prompt: str, schema: Type, strong: bool = False) -> dict:
        """Structured output validated by a pydantic model; returns a plain dict."""
        from google.genai import types
        self._pace()
        model = self.s.model_strong if strong else self.s.model_fast
        try:
            r = self.client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema, temperature=0.2))
            data = json.loads(r.text)
            return schema.model_validate(data).model_dump()
        except Exception as e:  # noqa: BLE001
            raise LLMError("gemini json call failed: %s" % type(e).__name__) from e

    def search(self, query: str) -> Tuple[str, List[str]]:
        """Google-Search-grounded answer: (text, source urls)."""
        from google.genai import types
        self._pace()
        try:
            r = self.client.models.generate_content(
                model=self.s.model_grounding, contents=query,
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
            urls: List[str] = []
            for c in (getattr(r, "candidates", None) or []):
                gm = getattr(c, "grounding_metadata", None)
                for ch in (getattr(gm, "grounding_chunks", None) or []):
                    u = getattr(getattr(ch, "web", None), "uri", None)
                    if u and u not in urls:
                        urls.append(u)
            return (r.text or ""), urls
        except Exception as e:  # noqa: BLE001
            raise LLMError("gemini grounding call failed: %s" % type(e).__name__) from e
