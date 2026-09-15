"""
Unit tests for OpenSearchSessionAuditRepository against a mocked OpenSearch
client (no live cluster needed - see test_search_integration.py for the
real-cluster equivalents, skipped automatically when unreachable).
"""

from datetime import datetime, timezone

import pytest

from app.repositories.opensearch_repository import OpenSearchSessionAuditRepository


def _hit(_id: str, source: dict, sort: list | None = None) -> dict:
    return {"_id": _id, "_source": source, "sort": sort or [1, _id]}


class _FakeOpenSearchClient:
    def __init__(self, hits: list[dict]):
        self._hits = hits

    async def search(self, index: str, body: dict) -> dict:
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
    repository = OpenSearchSessionAuditRepository(client)

    events, _ = await repository.query({"bool": {"filter": []}}, cursor=None, size=50)

    assert [e.id for e in events] == ["evt-good"]


@pytest.mark.asyncio
async def test_query_returns_all_events_when_none_malformed():
    client = _FakeOpenSearchClient(
        [_hit("evt-good", _VALID_SOURCE), _hit("evt-good-2", dict(_VALID_SOURCE, id="evt-good-2"))]
    )
    repository = OpenSearchSessionAuditRepository(client)

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
    repository = OpenSearchSessionAuditRepository(client)

    events, next_cursor = await repository.query(
        {"bool": {"filter": []}}, cursor=None, size=2
    )

    assert len(events) == 1
    assert next_cursor is not None
