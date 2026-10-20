from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.controllers.ingest_routes import build_ingest_router
from app.domains.sessions.domain import SESSIONS
from src.shared.models import SessionAuditEvent

API_KEY = "test-ingest-key"


class FakeRepository:
    """Stands in for OpenSearchAuditRepository.write_batch - returns
    whatever error list/None it's constructed with, regardless of the
    events actually passed in."""

    def __init__(self, errors=None):
        self._errors = errors
        self.received_events: list = []

    async def write_batch(self, events):
        self.received_events = list(events)
        return self._errors


def _make_event(id_: str = "evt-1") -> dict:
    return SessionAuditEvent(
        id=id_,
        org_id=7,
        session_id=1,
        kind="event",
        event_time=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _build_app(repository: FakeRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(build_ingest_router(SESSIONS))
    app.state.repositories = {SESSIONS.name: repository}
    return app


@pytest_asyncio.fixture
async def client_factory():
    async def _make(repository: FakeRepository):
        app = _build_app(repository)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_ingest_success_returns_200_and_received_count(client_factory):
    repository = FakeRepository(errors=None)
    client = await client_factory(repository)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/events",
            json=[_make_event("evt-1"), _make_event("evt-2")],
            headers={"X-API-Key": API_KEY},
        )

    assert resp.status_code == 200
    assert resp.json() == {"received": 2}


@pytest.mark.asyncio
async def test_ingest_empty_error_list_is_treated_as_full_success(client_factory):
    # write_batch's return type is `list | None` - an empty list must be
    # treated the same as None (`if not errors:`), not accidentally routed
    # down the 207 branch.
    repository = FakeRepository(errors=[])
    client = await client_factory(repository)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/events",
            json=[_make_event("evt-1")],
            headers={"X-API-Key": API_KEY},
        )

    assert resp.status_code == 200
    assert resp.json() == {"received": 1}


@pytest.mark.asyncio
async def test_ingest_partial_bulk_failure_returns_207_with_failed_ids_and_status(client_factory):
    # Shape matches opensearchpy's async_bulk error entries with
    # raise_on_error=False: {op_type: {..., "_id": ..., "error": {...}}}.
    errors = [
        {
            "index": {
                "_index": "audit_events-unlimited-2026.10",
                "_id": "evt-2",
                "status": 400,
                "error": {"type": "mapper_parsing_exception", "reason": "boom"},
            }
        }
    ]
    repository = FakeRepository(errors=errors)
    client = await client_factory(repository)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/events",
            json=[_make_event("evt-1"), _make_event("evt-2")],
            headers={"X-API-Key": API_KEY},
        )

    assert resp.status_code == 207
    body = resp.json()
    assert body["received"] == 1
    assert body["failed"] == [{"id": "evt-2", "status": 400}]


@pytest.mark.asyncio
async def test_ingest_missing_api_key_is_401(client_factory):
    repository = FakeRepository(errors=None)
    client = await client_factory(repository)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/events",
            json=[_make_event("evt-1")],
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_keeps_each_events_retention_and_defaults_a_missing_one_to_unlimited(
    client_factory,
):
    tiered_event = dict(_make_event("evt-tiered"), retention_days=90)
    event_without_retention = _make_event("evt-old-sender")
    del event_without_retention["retention_days"]
    repository = FakeRepository(errors=None)
    client = await client_factory(repository)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/events",
            json=[tiered_event, event_without_retention],
            headers={"X-API-Key": API_KEY},
        )

    assert resp.status_code == 200
    assert [(event.id, event.retention_days) for event in repository.received_events] == [
        ("evt-tiered", 90),
        ("evt-old-sender", 0),
    ]
