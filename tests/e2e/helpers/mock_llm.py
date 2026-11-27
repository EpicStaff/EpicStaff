"""Read the mock LLM's call log (`GET /__calls`) without clearing it.

The log is append-only and shared by every test, so a test takes a `marker()` (the current
number of calls) before the action it cares about and reads `calls_since(marker)` after.
That needs no clock agreement between the host and the mock-llm container. Markers are
positions in that never-cleared log, so the suite must never call `DELETE /__calls`:
clearing it would shift every other test's marker.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from helpers.redaction import scrub

MOCK_LLM_URL = os.environ.get("E2E_MOCK_LLM_URL", "http://localhost:18080").rstrip("/")
EMBEDDINGS_PATH = "/v1/embeddings"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class MockLlmClient:
    def __init__(self, base_url: str = MOCK_LLM_URL) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=10, trust_env=False)

    def close(self) -> None:
        self._http.close()

    def calls(self) -> list[dict]:
        response = self._http.get("/__calls")
        assert response.status_code == 200, f"mock-llm /__calls -> {response.status_code}: {scrub(response.text)[:500]}"
        return response.json()

    def marker(self) -> int:
        return len(self.calls())

    def calls_since(self, marker: int, path: str | None = None) -> list[dict]:
        return [call for call in self.calls()[marker:] if path is None or call["path"] == path]

    @contextmanager
    def embeddings_delayed(self, seconds: float) -> Iterator[None]:
        """Every embeddings reply waits `seconds` inside the block; back to 0 after it."""
        self._set_embeddings_delay(seconds)
        try:
            yield
        finally:
            self._set_embeddings_delay(0)

    def _set_embeddings_delay(self, seconds: float) -> None:
        response = self._http.put("/__embeddings_delay", params={"seconds": seconds})
        assert response.status_code == 200, (
            f"mock-llm /__embeddings_delay -> {response.status_code}: {scrub(response.text)[:500]}"
        )
