"""API tests for the three realtime voice config ViewSets' bulk delete.

The usage rules themselves are covered at service level
(tests/services_tests/test_realtime_config_delete_service.py). These pin the
HTTP wiring: the new routes exist and are permission-gated, and single DELETE now
runs the same usage guard as bulk -- a behaviour change on an endpoint the
frontend's Voice Configs section already calls.
"""

import pytest

from agents.models import AgentDefinition
from tables.models import Agent
from tables.models.rbac_models import (
    Organization,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tests.api_tests.bulk_delete_helpers import custom_role_client, org_admin_client

PROVIDERS = [
    pytest.param(
        OpenAIRealtimeConfig, "openai-realtime-configs", "openai_config", id="openai"
    ),
    pytest.param(
        ElevenLabsRealtimeConfig,
        "elevenlabs-realtime-configs",
        "elevenlabs_config",
        id="elevenlabs",
    ),
    pytest.param(
        GeminiRealtimeConfig, "gemini-realtime-configs", "gemini_config", id="gemini"
    ),
]


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _legacy_agent(org):
    return Agent.objects.create(org=org, role="voice", goal="g", backstory="b")


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_bulk_delete_route_deletes_an_unreferenced_config(
    django_user_model, org_a, config_model, route, fk
):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    config = config_model.objects.create(org=org_a, custom_name="cfg")

    resp = client.post(
        f"/api/{route}/bulk-delete/", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [config.id]
    assert not config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_bulk_delete_requires_delete_permission(
    django_user_model, org_a, config_model, route, fk
):
    client = custom_role_client(
        django_user_model,
        org_a,
        "reader@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    config = config_model.objects.create(org=org_a, custom_name="cfg")

    resp = client.post(
        f"/api/{route}/bulk-delete/", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 403
    assert config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_bulk_delete_another_orgs_config_is_not_found(
    django_user_model, org_a, org_b, config_model, route, fk
):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    other = config_model.objects.create(org=org_b, custom_name="other")

    resp = client.post(f"/api/{route}/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert resp.data["usage"] == {}
    assert config_model.objects.filter(id=other.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_dry_run_does_not_disclose_an_agent_the_caller_cannot_see(
    django_user_model, org_a, config_model, route, fk
):
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter3@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    hidden = AgentDefinition.objects.create(organization=org_a, name="secret agent")
    RealtimeAgentDefinition.objects.create(agent_definition=hidden, **{fk: config})

    resp = client.post(
        f"/api/{route}/bulk-delete/?dry_run=true", {"ids": [config.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped"] == [{"id": config.id, "reason": "in_use_restricted"}]
    assert resp.data["usage"][str(config.id)] == {
        "blocked": True,
        "by_resource_type": [
            {
                "resource_type": "agents",
                "visible_count": 0,
                "visible_sample": [],
                "truncated": False,
            }
        ],
    }
    assert config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_single_delete_is_blocked_by_an_agent_the_caller_cannot_see(
    django_user_model, org_a, config_model, route, fk
):
    """Single DELETE runs the same usage guard as bulk."""
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    RealtimeAgent.objects.create(agent=_legacy_agent(org_a), **{fk: config})

    resp = client.delete(f"/api/{route}/{config.id}/")

    assert resp.status_code == 403, resp.data
    assert resp.data["message"] == "in_use_restricted"
    assert config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,route,fk", PROVIDERS)
def test_single_delete_is_not_blocked_by_a_past_session(
    django_user_model, org_a, config_model, route, fk
):
    """A RealtimeAgentChat is a snapshot of past use, not a dependency."""
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter2@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    RealtimeAgentChat.objects.create(connection_key="past", **{fk: config})

    resp = client.delete(f"/api/{route}/{config.id}/")

    assert resp.status_code == 204, resp.data
    assert not config_model.objects.filter(id=config.id).exists()
