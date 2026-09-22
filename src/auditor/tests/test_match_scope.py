import os

# Settings() requires these at import time (no defaults) - set dummy values
# before anything under app.* gets imported, so this module is runnable on
# its own without a real .env file (mirrors what docker-compose injects).
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

from datetime import datetime, timezone

import pytest

from app.services.matching import mark_filter_matched
from src.shared.models import SessionAuditEvent


def _event(event_id: str, org_id: int = 7) -> SessionAuditEvent:
    return SessionAuditEvent(
        id=event_id,
        session_id=1,
        kind="event",
        event_time=datetime.now(timezone.utc),
        org_id=org_id,
    )


@pytest.mark.asyncio
async def test_mark_filter_matched_flags_only_matched_ids():
    events = [_event("evt-1"), _event("evt-2"), _event("evt-3")]
    matched_ids = {"evt-1", "evt-3"}

    result = await mark_filter_matched(events, matched_ids)

    by_id = {e.id: e.filter_matched for e in result}
    assert by_id == {"evt-1": True, "evt-2": False, "evt-3": True}


@pytest.mark.asyncio
async def test_mark_filter_matched_defaults_all_false_when_no_ids_match():
    events = [_event("evt-1"), _event("evt-2")]

    result = await mark_filter_matched(events, matched_ids=set())

    assert all(e.filter_matched is False for e in result)


@pytest.mark.asyncio
async def test_mark_filter_matched_returns_same_list_mutated_in_place():
    events = [_event("evt-1")]

    result = await mark_filter_matched(events, matched_ids={"evt-1"})

    assert result is events
    assert events[0].filter_matched is True


@pytest.mark.asyncio
async def test_mark_filter_matched_empty_events_is_noop():
    result = await mark_filter_matched([], matched_ids={"evt-1"})
    assert result == []
