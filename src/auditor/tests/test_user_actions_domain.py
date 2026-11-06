import pytest
from httpx import ASGITransport, AsyncClient

import app.main as auditor_main
from app.domains.registry import ALL_DOMAINS, enabled_domains
from app.domains.sessions.index import SESSIONS_INDEX
from app.domains.user_actions.index import USER_ACTIONS_INDEX


class _AcceptingRepository:
    async def write_batch(self, events):
        return None


@pytest.mark.parametrize(
    ("sessions_enabled", "user_actions_enabled", "expected"),
    [
        (False, False, set()),
        (True, False, {"sessions"}),
        (False, True, {"user_actions"}),
        (True, True, {"sessions", "user_actions"}),
    ],
)
def test_enabled_domains_returns_only_switched_on(sessions_enabled, user_actions_enabled, expected):
    domains = enabled_domains(
        sessions_enabled=sessions_enabled, user_actions_enabled=user_actions_enabled
    )

    assert set(domains) == expected
    assert all(domains[name] is ALL_DOMAINS[name] for name in expected)


def test_user_actions_index_names_do_not_overlap_sessions():
    assert USER_ACTIONS_INDEX.name == "audit_user_actions"
    assert USER_ACTIONS_INDEX.name.startswith("audit_events-") is False
    assert SESSIONS_INDEX.name.startswith(f"{USER_ACTIONS_INDEX.name}-") is False
    assert USER_ACTIONS_INDEX.ism_policy_prefix != SESSIONS_INDEX.ism_policy_prefix


@pytest.mark.asyncio
async def test_ingest_user_actions_route_absent_when_disabled(monkeypatch):
    monkeypatch.setattr(
        auditor_main,
        "DOMAINS",
        enabled_domains(sessions_enabled=True, user_actions_enabled=False),
    )
    app = auditor_main.create_app()
    app.state.repositories = {"sessions": _AcceptingRepository()}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        user_actions = await client.post(
            "/auditor/api/audit/user_actions/events", json=[], headers={"X-API-Key": "test-ingest-key"}
        )
        sessions = await client.post(
            "/auditor/api/audit/sessions/events", json=[], headers={"X-API-Key": "test-ingest-key"}
        )

    assert user_actions.status_code == 404
    assert sessions.status_code == 200
