from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opensearchpy.exceptions import RequestError as OpenSearchRequestError

from app.controllers.query_routes import build_search_router
from app.domains.sessions.domain import SESSIONS
from app.main import register_exception_handlers
from src.shared.models import SessionAuditEvent
from tests._auth import auth
from tests._fakes import InMemoryFakeRepository

pytestmark = pytest.mark.asyncio

ORG_ID = 7
NOW = datetime.now(timezone.utc)
SEARCH_PATH = "/api/audit/sessions/search"


class RaisingRepository:
    """Stands in for the OpenSearch repository, failing the way OpenSearch does."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def query(self, compiled_query, cursor=None, size=50):
        raise self._exc


def _client(repository) -> AsyncClient:
    app = FastAPI()
    app.include_router(build_search_router(SESSIONS))
    register_exception_handlers(app)
    app.state.repositories = {SESSIONS.name: repository}
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test", headers=auth())


def _opensearch_error(error: dict) -> OpenSearchRequestError:
    return OpenSearchRequestError(400, error["type"], {"error": error, "status": 400})


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail", "must_not_leak"),
    [
        (
            {
                "root_cause": [{"type": "search_phase_execution_exception", "reason": "all shards failed"}],
                "type": "search_phase_execution_exception",
                "reason": "all shards failed",
                "caused_by": {
                    "type": "illegal_argument_exception",
                    "reason": "failed to parse date field [2026.09.09] with format "
                    "[strict_date_optional_time||epoch_millis]",
                },
            },
            400,
            "failed to parse date field [2026.09.09] with format "
            "[strict_date_optional_time||epoch_millis]",
            "search_phase_execution_exception",
        ),
        (
            {
                "root_cause": [{"type": "parse_exception", "reason": "root cause reason"}],
                "type": "parse_exception",
                "reason": "top level reason",
            },
            400,
            "root cause reason",
            "top level reason",
        ),
        (
            {
                "root_cause": [{"type": "query_shard_exception", "reason": "failed to create query"}],
                "type": "search_phase_execution_exception",
                "reason": "all shards failed",
                "caused_by": {"type": "number_format_exception", "reason": 'For input string: "abc"'},
            },
            400,
            'For input string: "abc"',
            "query_shard_exception",
        ),
        (
            # A malformed DSL body is this service's own compiler's fault, not the
            # caller's - even when OpenSearch nests an illegal_argument_exception.
            {
                "root_cause": [{"type": "parsing_exception", "reason": "unknown query [wildcrd]"}],
                "type": "x_content_parse_exception",
                "reason": "[1:10] [bool] failed to parse field [filter]",
                "caused_by": {"type": "illegal_argument_exception", "reason": "internal detail"},
            },
            500,
            "Internal server error",
            "internal detail",
        ),
    ],
    ids=[
        "bad-date-reports-the-caused-by-reason",
        "falls-back-to-the-root-cause",
        "bad-number-from-the-client",
        "own-dsl-error-is-a-500",
    ],
)
async def test_opensearch_rejection_is_reported_without_leaking_internals(
    error, expected_status, expected_detail, must_not_leak
):
    async with _client(RaisingRepository(_opensearch_error(error))) as client:
        response = await client.post(
            SEARCH_PATH, json={"filters": {"field": "status", "op": "equals", "value": "failed"}}
        )

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    assert must_not_leak not in response.text


async def test_opensearch_error_without_a_body_is_a_500_without_leaking():
    """Nothing ties the failure to the caller's input, so it is not blamed on them."""
    async with _client(RaisingRepository(OpenSearchRequestError(400, "some_error", None))) as client:
        response = await client.post(
            SEARCH_PATH, json={"filters": {"field": "status", "op": "equals", "value": "failed"}}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def _tree_events() -> list[SessionAuditEvent]:
    """A session tree (session -> node -> event) plus another session's event."""
    return [
        SessionAuditEvent(
            id="sess-1", parent_id="", session_id=100, kind="session",
            status="failed", event_time=NOW, org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="node-1", parent_id="sess-1", session_id=100, kind="node",
            status="failed", event_time=NOW + timedelta(seconds=1), org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-1", parent_id="node-1", session_id=100, kind="event",
            status="failed", event_time=NOW + timedelta(seconds=2), org_id=ORG_ID,
        ),
        SessionAuditEvent(
            id="evt-other", parent_id="", session_id=200, kind="event",
            status="failed", event_time=NOW, org_id=ORG_ID,
        ),
    ]


async def _search(events, body) -> dict[str, bool]:
    """Search over `events`; returns each returned row's filter_matched flag by id."""
    async with _client(InMemoryFakeRepository(events)) as client:
        response = await client.post(SEARCH_PATH, json=body)
    assert response.status_code == 200
    return {item["id"]: item["filter_matched"] for item in response.json()["items"]}


async def test_search_never_returns_another_orgs_events():
    """The org scope comes from the token: an event of org 999 matching the filter
    stays out only if the token's org_id was compiled into the query."""
    other_org_event = SessionAuditEvent(
        id="evt-other-org", parent_id="", session_id=100, kind="event",
        status="failed", event_time=NOW, org_id=999,
    )

    found = await _search(
        _tree_events() + [other_org_event],
        {"filters": {"field": "session_id", "op": "equals", "value": 100}},
    )

    assert set(found) == {"sess-1", "node-1", "evt-1"}


@pytest.mark.parametrize("size", [0, -1, 1001])
async def test_search_rejects_out_of_range_size_with_422(size):
    async with _client(InMemoryFakeRepository(_tree_events())) as client:
        response = await client.post(SEARCH_PATH, json={"size": size})

    assert response.status_code == 422
