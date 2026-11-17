"""The value-list route, over HTTP with real tokens and the in-memory repository."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.main as auditor_main
from app.controllers.domain_router import build_domain_router
from app.domains.registry import enabled_domains
from app.domains.user_actions.domain import USER_ACTIONS
from app.main import register_exception_handlers
from src.shared.models import UserActionEvent
from tests._auth import auth
from tests._fakes import InMemoryFakeRepository

pytestmark = pytest.mark.asyncio

ORG_ID = 7
NOW = datetime.now(timezone.utc)
VALUES_PATH = "/api/audit/user_actions/values/target_type"
USER_AUDIT_READER = {"AUDIT": None, "USER_AUDIT": ["read"]}


def _event(event_id: str, target_type: str | None, *, org_id: int = ORG_ID, age_days: int = 0):
    return UserActionEvent(
        id=event_id,
        org_id=org_id,
        event_time=NOW - timedelta(days=age_days),
        actor_user_id=1,
        actor_email="user@example.com",
        action="created",
        target_type=target_type,
    )


def _client(events: list[UserActionEvent], **claims) -> AsyncClient:
    app = FastAPI()
    app.include_router(build_domain_router(USER_ACTIONS))
    register_exception_handlers(app)
    app.state.repositories = {USER_ACTIONS.name: InMemoryFakeRepository(events)}
    headers = auth(**{**USER_AUDIT_READER, **claims})
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


async def _values(events: list[UserActionEvent], **claims) -> list[str]:
    async with _client(events, **claims) as client:
        response = await client.get(VALUES_PATH)
    assert response.status_code == 200
    assert response.json()["field"] == "target_type"
    return response.json()["values"]


async def test_lists_distinct_non_empty_values_sorted():
    events = [
        _event("ua-1", "python node"),
        _event("ua-2", "agent"),
        _event("ua-3", "flow"),
        _event("ua-4", "agent"),
        _event("ua-5", None),
        _event("ua-6", ""),
    ]

    assert await _values(events) == ["agent", "flow", "python node"]


async def test_leaves_out_values_only_another_org_recorded():
    events = [_event("ua-1", "flow"), _event("ua-other-org", "member", org_id=999)]

    assert await _values(events) == ["flow"]


async def test_leaves_out_values_only_recorded_before_the_retention_window():
    events = [
        _event("ua-recent", "flow", age_days=10),
        _event("ua-expired", "storage", age_days=40),
    ]

    assert await _values(events, retention_days=30) == ["flow"]
    assert await _values(events, retention_days=0) == ["flow", "storage"]


@pytest.mark.parametrize("field", ["action", "actor_email", "no_such_field"])
async def test_field_without_a_value_list_is_404(field):
    async with _client([_event("ua-1", "flow")]) as client:
        response = await client.get(f"/api/audit/user_actions/values/{field}")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        f"Field {field!r} has no value list in the user_actions audit domain"
    )


@pytest.mark.parametrize(
    "claims",
    [
        {"USER_AUDIT": ["export"]},
        {"USER_AUDIT": None, "AUDIT": ["read"]},
        {"org_id": None},
        {"retention_days": None},
    ],
    ids=["export-only", "sessions-grant-only", "missing-org", "missing-retention"],
)
async def test_rejects_a_token_exactly_as_search_does(claims):
    async with _client([_event("ua-1", "flow")], **claims) as client:
        search = await client.post("/api/audit/user_actions/search", json={})
        values = await client.get(VALUES_PATH)

    assert search.status_code in (401, 403)
    assert (values.status_code, values.json()) == (search.status_code, search.json())


async def test_sessions_domain_has_no_values_route(monkeypatch):
    monkeypatch.setattr(
        auditor_main,
        "DOMAINS",
        enabled_domains(sessions_enabled=True, user_actions_enabled=True),
    )
    app = auditor_main.create_app()
    app.state.repositories = {"user_actions": InMemoryFakeRepository([_event("ua-1", "flow")])}
    headers = auth(AUDIT=["read"], USER_AUDIT=["read"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        sessions = await client.get("/auditor/api/audit/sessions/values/status")
        user_actions = await client.get(f"/auditor{VALUES_PATH}")

    assert (sessions.status_code, sessions.json()) == (404, {"detail": "Not Found"})
    assert user_actions.status_code == 200
