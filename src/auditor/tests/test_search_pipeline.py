import os

# See test_query_routes.py's header comment - same reasoning.
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("AUDIT_JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_USER", "test")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

from datetime import datetime, timezone

import pytest

from app.domains.sessions.domain import SESSIONS
from app.services.search_pipeline import SearchPipeline
from src.shared.models import SessionAuditEvent


def _make_event(id_: str) -> SessionAuditEvent:
    return SessionAuditEvent(
        id=id_, session_id=1, kind="event", event_time=datetime.now(timezone.utc), org_id=7
    )


class _MidScanEmptyPageRepository:
    """Simulates a repository whose middle page comes back empty (e.g. every
    document on that page failed to deserialize) while OpenSearch's cursor
    still points at further, non-empty pages."""

    def __init__(self, pages: list[tuple[list[SessionAuditEvent], str | None]]):
        self._pages = pages
        self.calls = 0

    async def query(self, compiled_query: dict, cursor: str | None = None, size: int = 200):
        page = self._pages[self.calls]
        self.calls += 1
        return page


@pytest.mark.asyncio
async def test_scan_all_does_not_stop_on_an_empty_page_with_a_follow_up_cursor():
    pipeline = SearchPipeline.from_domain(SESSIONS)
    repository = _MidScanEmptyPageRepository(
        [
            ([_make_event("e1"), _make_event("e2")], "cursor-1"),
            ([], "cursor-2"),  # empty page, but more pages remain
            ([_make_event("e3")], None),
        ]
    )

    collected = []
    async for page in pipeline._scan_all(repository, compiled_query={}):
        collected.extend(page)

    assert [e.id for e in collected] == ["e1", "e2", "e3"]
    assert repository.calls == 3
