"""
Unit tests for OpenSearchAuditRepository against a mocked OpenSearch
client (no live cluster needed - see test_search_integration.py for the
real-cluster equivalents, skipped automatically when unreachable).
"""

from datetime import datetime, timezone

import pytest

from app.domains.sessions.index import SESSIONS_INDEX
from app.repositories.opensearch_repository import OpenSearchAuditRepository
from src.shared.models import SessionAuditEvent


def _hit(_id: str, source: dict, sort: list | None = None) -> dict:
    return {"_id": _id, "_source": source, "sort": sort or [1, _id]}


class _FakeOpenSearchClient:
    def __init__(self, hits: list[dict]):
        self._hits = hits
        self.last_body: dict | None = None

    async def search(self, index: str, body: dict) -> dict:
        self.last_body = body
        return {"hits": {"hits": self._hits}}


_VALID_SOURCE = {
    "id": "evt-good",
    "org_id": 1,
    "kind": "event",
    "parent_id": "",
    "session_id": 1,
    "name": "",
    "status": "completed",
    "event_time": datetime.now(timezone.utc).isoformat(),
}


@pytest.mark.asyncio
async def test_query_skips_malformed_status_without_raising():
    """A document with a `status` outside the SessionAuditEvent Literal
    (e.g. a legacy/manually-written value) must not 500 the whole page -
    it should be skipped, and every other valid row on the same page must
    still come back."""
    bad_source = dict(_VALID_SOURCE, id="evt-bad", status="warning")
    client = _FakeOpenSearchClient(
        [_hit("evt-good", _VALID_SOURCE), _hit("evt-bad", bad_source)]
    )
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    events, _ = await repository.query({"bool": {"filter": []}}, cursor=None, size=50)

    assert [e.id for e in events] == ["evt-good"]


@pytest.mark.asyncio
async def test_query_returns_all_events_when_none_malformed():
    client = _FakeOpenSearchClient(
        [
            _hit("evt-good", _VALID_SOURCE),
            _hit("evt-good-2", dict(_VALID_SOURCE, id="evt-good-2")),
        ]
    )
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    events, _ = await repository.query({"bool": {"filter": []}}, cursor=None, size=50)

    assert {e.id for e in events} == {"evt-good", "evt-good-2"}


@pytest.mark.asyncio
async def test_query_next_cursor_still_advances_when_a_row_is_skipped():
    """next_cursor is derived from the raw `hits` (size-based), not from the
    filtered `events` list - a skipped malformed row must not desync
    pagination for the caller."""
    bad_source = dict(_VALID_SOURCE, id="evt-bad", status="warning")
    hits = [_hit("evt-good", _VALID_SOURCE), _hit("evt-bad", bad_source)]
    client = _FakeOpenSearchClient(hits)
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    events, next_cursor = await repository.query(
        {"bool": {"filter": []}}, cursor=None, size=2
    )

    assert len(events) == 1
    assert next_cursor is not None


@pytest.mark.asyncio
async def test_query_disables_exact_total_hit_tracking():
    """Pagination here is search_after/next_cursor-based and the API
    response never exposes a hit count - exact total tracking would force
    OpenSearch to visit every matching document (worst case on broad
    negation queries) just to produce a number nobody reads."""
    client = _FakeOpenSearchClient([_hit("evt-good", _VALID_SOURCE)])
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    await repository.query({"bool": {"filter": []}}, cursor=None, size=50)

    assert client.last_body["track_total_hits"] is False


@pytest.mark.asyncio
async def test_query_with_no_hits_and_size_zero_does_not_raise():
    client = _FakeOpenSearchClient([])
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    events, next_cursor = await repository.query({"bool": {"filter": []}}, cursor=None, size=0)

    assert events == []
    assert next_cursor is None
