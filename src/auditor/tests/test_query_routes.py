import os

# The auditor settings module requires these at import time (no defaults) -
# set dummy values before anything under app.* gets imported, so this module
# is runnable on its own without a real .env file (mirrors what docker-compose injects).
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("AUDIT_JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opensearchpy.exceptions import RequestError as OpenSearchRequestError

from app.controllers.query_routes import build_search_router
from app.core.security import verify_user_jwt
from app.domains.sessions.domain import SESSIONS
from app.main import register_exception_handlers
from src.shared.models import SessionAuditEvent
from tests._fakes import InMemoryFakeRepository

DEFAULT_CLAIMS = {"org_id": 7, "user_id": 42, "AUDIT": ["read"], "retention_days": 0}

# Shape OpenSearch actually returns for a rejected date-format query on
# `event_time < "2026.09.09"` (dots instead of dashes) - a
# search_phase_execution_exception whose `caused_by` carries the real reason.
DATE_FORMAT_ERROR_BODY = {
    "error": {
        "root_cause": [
            {
                "type": "search_phase_execution_exception",
                "reason": "all shards failed",
            }
        ],
        "type": "search_phase_execution_exception",
        "reason": "all shards failed",
        "caused_by": {
            "type": "illegal_argument_exception",
            "reason": (
                "failed to parse date field [2026.09.09] with format "
                "[strict_date_optional_time||epoch_millis]"
            ),
        },
    },
    "status": 400,
}


class RaisingRepository:
    """Stands in for SessionAuditRepository - raises whatever exception the
    test wires up instead of hitting real OpenSearch."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def query(self, compiled_query, cursor=None, size=50):
        raise self._exc


def _build_app(exc: Exception) -> FastAPI:
    app = FastAPI()
    app.include_router(build_search_router(SESSIONS))
    register_exception_handlers(app)
    app.state.repositories = {SESSIONS.name: RaisingRepository(exc)}
    app.dependency_overrides[verify_user_jwt] = lambda: dict(DEFAULT_CLAIMS)
    return app


@pytest_asyncio.fixture
async def client_with_exc():
    async def _make(exc: Exception):
        app = _build_app(exc)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_malformed_date_filter_returns_400_not_500(client_with_exc):
    exc = OpenSearchRequestError(
        400, "search_phase_execution_exception", DATE_FORMAT_ERROR_BODY
    )
    async with await client_with_exc(exc) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={
                "filters": {"field": "event_time", "op": "lt", "value": "2026.09.09"}
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    assert "failed to parse date field [2026.09.09]" in body["detail"]
    # The raw exception repr (status code, error type, full nested body) must
    # not leak to the client - only the extracted human-readable reason.
    assert "search_phase_execution_exception" not in body["detail"]


@pytest.mark.asyncio
async def test_opensearch_error_without_caused_by_falls_back_to_root_cause(
    client_with_exc,
):
    body = {
        "error": {
            "root_cause": [{"type": "parse_exception", "reason": "root cause reason"}],
            "type": "parse_exception",
            "reason": "top level reason",
        },
        "status": 400,
    }
    exc = OpenSearchRequestError(400, "parse_exception", body)
    async with await client_with_exc(exc) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "status", "op": "equals", "value": "failed"}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "root cause reason"


@pytest.mark.asyncio
async def test_opensearch_error_with_unattributable_info_is_500_without_leaking(
    client_with_exc,
):
    # No parseable error body means nothing ties the failure to client input,
    # so it must not be blamed on the caller - and the raw text must not leak.
    exc = OpenSearchRequestError(400, "some_error", None)
    async with await client_with_exc(exc) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "status", "op": "equals", "value": "failed"}},
        )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error"


@pytest.mark.asyncio
async def test_opensearch_dsl_parsing_error_is_500_not_400(client_with_exc):
    # A malformed DSL body is something this service's compiler produced, not
    # the caller - even when OpenSearch nests an illegal_argument_exception.
    body = {
        "error": {
            "root_cause": [{"type": "parsing_exception", "reason": "unknown query [wildcrd]"}],
            "type": "x_content_parse_exception",
            "reason": "[1:10] [bool] failed to parse field [filter]",
            "caused_by": {"type": "illegal_argument_exception", "reason": "internal detail"},
        },
        "status": 400,
    }
    exc = OpenSearchRequestError(400, "x_content_parse_exception", body)
    async with await client_with_exc(exc) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "status", "op": "equals", "value": "failed"}},
        )

    assert resp.status_code == 500
    assert "internal detail" not in resp.text


@pytest.mark.asyncio
async def test_opensearch_number_format_error_from_client_value_is_400(client_with_exc):
    body = {
        "error": {
            "root_cause": [
                {"type": "query_shard_exception", "reason": "failed to create query"}
            ],
            "type": "search_phase_execution_exception",
            "reason": "all shards failed",
            "caused_by": {
                "type": "number_format_exception",
                "reason": 'For input string: "abc"',
            },
        },
        "status": 400,
    }
    exc = OpenSearchRequestError(400, "search_phase_execution_exception", body)
    async with await client_with_exc(exc) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "session_id", "op": "equals", "value": "abc"}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == 'For input string: "abc"'


# --- filter_matched (mark_filter_matched wired through /sessions/search) ---

ORG_ID = 7
NOW = datetime.now(timezone.utc)


def _tree_events() -> list[SessionAuditEvent]:
    """One full session tree - session doc -> node doc -> event doc - plus
    an unrelated session's event, so tests can assert the unrelated one
    never gets pulled in by expansion."""
    return [
        SessionAuditEvent(
            id="sess-1",
            parent_id="",
            session_id=100,
            kind="session",
            status="failed",
            event_time=NOW,
            org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="node-1",
            parent_id="sess-1",
            session_id=100,
            kind="node",
            status="failed",
            event_time=NOW + timedelta(seconds=1),
            org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-1",
            parent_id="node-1",
            session_id=100,
            kind="event",
            status="failed",
            event_time=NOW + timedelta(seconds=2),
            org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-other",
            parent_id="",
            session_id=200,
            kind="event",
            status="failed",
            event_time=NOW,
            org_id=ORG_ID,
        ),
    ]


def _build_search_app(events: list[SessionAuditEvent]) -> FastAPI:
    app = FastAPI()
    app.include_router(build_search_router(SESSIONS))
    app.state.repositories = {SESSIONS.name: InMemoryFakeRepository(events)}
    app.dependency_overrides[verify_user_jwt] = lambda: dict(DEFAULT_CLAIMS)
    return app


@pytest_asyncio.fixture
async def search_client():
    async def _make(events: list[SessionAuditEvent]):
        app = _build_search_app(events)
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_no_match_scope_all_returned_events_are_filter_matched(search_client):
    # Two rows match the filter directly (status=failed matches all 4 fixture
    # rows, so scope it to session_id=100 to get exactly the tree's 3 rows) -
    # with no match_scope expansion, every returned row IS a match.
    async with await search_client(_tree_events()) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "session_id", "op": "equals", "value": 100}},
        )

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["id"] for i in items} == {"sess-1", "node-1", "evt-1"}
    assert all(i["filter_matched"] is True for i in items)


@pytest.mark.asyncio
async def test_children_expansion_flags_only_originally_matched_rows(search_client):
    # Filter matches only the session doc; match_scope.children pulls in the
    # rest of its tree (node-1, evt-1) as unmatched expansion rows.
    async with await search_client(_tree_events()) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={
                "filters": {"field": "id", "op": "equals", "value": "sess-1"},
                "match_scope": {"children": True},
            },
        )

    assert resp.status_code == 200
    items = {i["id"]: i["filter_matched"] for i in resp.json()["items"]}
    assert items == {"sess-1": True, "node-1": False, "evt-1": False}


@pytest.mark.asyncio
async def test_search_never_returns_another_orgs_events(search_client):
    """Positive assertion that the token's real org_id is actually compiled
    into the query and enforced - not just that a missing org_id fails.
    InMemoryFakeRepository evaluates the compiled `bool.filter` clauses
    against every stored event, so an event belonging to a different org
    only stays out of the results if ScopingPolicy actually injected a
    `{"term": {"org_id": 7}}` clause (DEFAULT_CLAIMS.org_id) into the query."""
    events = _tree_events() + [
        SessionAuditEvent(
            id="evt-other-org",
            parent_id="",
            session_id=100,
            kind="event",
            status="failed",
            event_time=NOW,
            org_id=999,
        )
    ]
    async with await search_client(events) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "session_id", "op": "equals", "value": 100}},
        )

    assert resp.status_code == 200
    ids = {i["id"] for i in resp.json()["items"]}
    assert ids == {"sess-1", "node-1", "evt-1"}
    assert "evt-other-org" not in ids


@pytest.mark.asyncio
async def test_search_rejects_token_missing_retention_days_claim(search_client):
    """A malformed/incomplete token (missing the retention_days claim
    entirely) must be rejected with 401, not silently treated as
    retention_days=0 (which this service's convention reads as "unlimited
    retention" - the maximally permissive interpretation)."""
    app = _build_search_app(_tree_events())
    claims_without_retention = {
        k: v for k, v in DEFAULT_CLAIMS.items() if k != "retention_days"
    }
    app.dependency_overrides[verify_user_jwt] = lambda: dict(claims_without_retention)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={"filters": {"field": "session_id", "op": "equals", "value": 100}},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_full_session_history_flags_original_matches_despite_refetch(
    search_client,
):
    # full_session_history re-fetches the whole session via a fresh query
    # (InMemoryFakeRepository returns model_copy() instances, mirroring how a
    # real OpenSearch round-trip always produces brand-new SessionAuditEvent
    # objects) - confirms evt-1 still comes back flagged as the original
    # match even though it's a different Python object post-refetch, per the
    # id-based design of mark_filter_matched/match_scope.py.
    async with await search_client(_tree_events()) as client:
        resp = await client.post(
            "/api/audit/sessions/search",
            json={
                "filters": {"field": "id", "op": "equals", "value": "evt-1"},
                "match_scope": {"full_session_history": True},
            },
        )

    assert resp.status_code == 200
    items = {i["id"]: i["filter_matched"] for i in resp.json()["items"]}
    assert items == {"sess-1": False, "node-1": False, "evt-1": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -1, 1001])
async def test_search_rejects_out_of_range_size_with_422(search_client, size):
    async with await search_client(_tree_events()) as client:
        resp = await client.post("/api/audit/sessions/search", json={"size": size})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_rejects_token_granting_read_on_another_resource_only():
    app = _build_search_app(_tree_events())
    app.dependency_overrides[verify_user_jwt] = lambda: {
        "org_id": ORG_ID,
        "user_id": 42,
        "retention_days": 0,
        "BILLING": ["read"],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/search", json={})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_search_rejects_legacy_flat_actions_claim():
    app = _build_search_app(_tree_events())
    app.dependency_overrides[verify_user_jwt] = lambda: {
        "org_id": ORG_ID,
        "user_id": 42,
        "retention_days": 0,
        "actions": ["read"],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/search", json={})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_search_rejects_malformed_resource_claim():
    app = _build_search_app(_tree_events())
    app.dependency_overrides[verify_user_jwt] = lambda: {
        "org_id": ORG_ID,
        "user_id": 42,
        "retention_days": 0,
        "AUDIT": "read",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/search", json={})

    assert resp.status_code == 403
