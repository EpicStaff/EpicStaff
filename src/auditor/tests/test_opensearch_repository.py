"""
Unit tests for OpenSearchAuditRepository against a mocked OpenSearch
client (no live cluster needed - see test_search_integration.py for the
real-cluster equivalents, skipped automatically when unreachable).
"""

from datetime import datetime, timedelta, timezone

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
        self.searched_indices: list[str] = []

    async def search(self, index: str, body: dict) -> dict:
        self.last_body = body
        self.searched_indices.append(index)
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
async def test_malformed_document_is_skipped_without_breaking_the_page_or_pagination():
    """A `status` outside the SessionAuditEvent Literal (a legacy or hand-written
    value) must not 500 the whole page - the row is skipped, the rest come back."""
    bad_source = dict(_VALID_SOURCE, id="evt-bad", status="warning")
    client = _FakeOpenSearchClient(
        [_hit("evt-good", _VALID_SOURCE), _hit("evt-bad", bad_source)]
    )
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    events, next_cursor = await repository.query({"bool": {"filter": []}}, cursor=None, size=2)

    assert [e.id for e in events] == ["evt-good"]
    # The cursor follows the raw hits, so a skipped row does not end pagination early.
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


@pytest.mark.asyncio
async def test_written_document_keeps_the_events_retention_days(monkeypatch):
    indexed_sources: list[dict] = []

    async def recording_bulk(client, actions, raise_on_error):
        indexed_sources.extend(action["_source"] for action in actions)
        return len(indexed_sources), []

    monkeypatch.setattr("app.repositories.opensearch_repository.async_bulk", recording_bulk)
    repository = OpenSearchAuditRepository(
        _FakeOpenSearchClient([]), SESSIONS_INDEX, SessionAuditEvent
    )
    event = SessionAuditEvent(
        id="evt-tiered", org_id=1, session_id=1, kind="event",
        event_time=datetime.now(timezone.utc), retention_days=90,
    )

    assert await repository.write_batch([event]) is None
    assert [source["retention_days"] for source in indexed_sources] == [90]


@pytest.mark.asyncio
async def test_search_reads_the_pattern():
    client = _FakeOpenSearchClient([_hit("evt-good", _VALID_SOURCE)])
    repository = OpenSearchAuditRepository(client, SESSIONS_INDEX, SessionAuditEvent)

    await repository.query({"bool": {"filter": []}}, cursor=None, size=50)

    assert client.searched_indices == ["audit_events-*"]


@pytest.mark.asyncio
async def test_write_batch_routes_each_event_to_its_index(monkeypatch):
    received_at = datetime(2026, 10, 31, 23, 59, 30, tzinfo=timezone.utc)
    index_by_id: dict[str, str] = {}
    record_time_by_id: dict[str, str] = {}

    async def recording_bulk(client, actions, raise_on_error):
        for action in actions:
            index_by_id[action["_id"]] = action["_index"]
            record_time_by_id[action["_id"]] = action["_source"]["record_time"]
        return len(index_by_id), []

    monkeypatch.setattr("app.repositories.opensearch_repository.async_bulk", recording_bulk)
    repository = OpenSearchAuditRepository(
        _FakeOpenSearchClient([]), SESSIONS_INDEX, SessionAuditEvent, clock=lambda: received_at
    )
    skewed_event_time = received_at + timedelta(days=61)
    events = [
        SessionAuditEvent(
            id=event_id, org_id=1, session_id=1, kind="event",
            event_time=skewed_event_time, retention_days=retention_days,
        )
        for event_id, retention_days in [("evt-30", 30), ("evt-forever", 0), ("evt-365", 365)]
    ]

    assert await repository.write_batch(events) is None
    assert index_by_id == {
        "evt-30": "audit_events-30d-2026.10",
        "evt-forever": "audit_events-unlimited-2026.10",
        "evt-365": "audit_events-365d-2026.10",
    }
    assert set(record_time_by_id.values()) == {"2026-10-31T23:59:30Z"}
