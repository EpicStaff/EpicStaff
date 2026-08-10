"""EST-3629 — RBAC/org-scoping on the three provider realtime-config
endpoints (OpenAI / ElevenLabs / Gemini), plus EST-3630 — RealtimeChannel
must not accept a cross-org RealtimeAgent.

Follows the org_a/org_b + client_member pattern from
test_org_scoping_global_runtime.py.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.models import Agent
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
)
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.models.webhook_models import RealtimeChannel


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _org_admin(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_org_b(db, django_user_model, org_b):
    return _client(_org_admin(django_user_model, org_b, "orgb-admin@example.com"), org_b)


# ---------------------------------------------------------------------------
# Per-model config (url basename, model class, minimal create payload)
# ---------------------------------------------------------------------------

CONFIG_CASES = [
    pytest.param(
        "openairealtimeconfig",
        OpenAIRealtimeConfig,
        {"custom_name": "openai-cfg"},
        id="openai",
    ),
    pytest.param(
        "elevenlabsrealtimeconfig",
        ElevenLabsRealtimeConfig,
        {"custom_name": "elevenlabs-cfg"},
        id="elevenlabs",
    ),
    pytest.param(
        "geminirealtimeconfig",
        GeminiRealtimeConfig,
        {"custom_name": "gemini-cfg"},
        id="gemini",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("basename, model, payload", CONFIG_CASES)
def test_provider_config_cross_org_404(
    auth_client, org_b, basename, model, payload
):
    instance = model.objects.create(org=org_b, **payload)
    url = reverse(f"{basename}-detail", args=[instance.pk])
    assert auth_client.get(url).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("basename, model, payload", CONFIG_CASES)
def test_provider_config_own_org_visible(
    auth_client, default_org, basename, model, payload
):
    instance = model.objects.create(org=default_org, **payload)
    url = reverse(f"{basename}-detail", args=[instance.pk])
    assert auth_client.get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("basename, model, payload", CONFIG_CASES)
def test_provider_config_list_excludes_other_org(
    auth_client, default_org, org_b, basename, model, payload
):
    own = model.objects.create(org=default_org, **payload)
    model.objects.create(org=org_b, **payload)
    url = reverse(f"{basename}-list")
    resp = auth_client.get(url)
    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.data["results"]}
    assert returned_ids == {own.id}


@pytest.mark.django_db
@pytest.mark.parametrize("basename, model, payload", CONFIG_CASES)
def test_provider_config_create_stamps_org(
    auth_client, default_org, basename, model, payload
):
    url = reverse(f"{basename}-list")
    resp = auth_client.post(url, payload, format="json")
    assert resp.status_code == 201, resp.data
    instance = model.objects.get(pk=resp.data["id"])
    assert instance.org_id == default_org.id


@pytest.mark.django_db
@pytest.mark.parametrize("basename, model, payload", CONFIG_CASES)
def test_provider_config_update_cross_org_rejected(
    client_org_b, org_b, default_org, basename, model, payload
):
    # A member of org_b must not be able to update a config owned by another org.
    instance = model.objects.create(org=default_org, **payload)
    url = reverse(f"{basename}-detail", args=[instance.pk])
    resp = client_org_b.patch(url, {"custom_name": "hacked"}, format="json")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# EST-3630 — RealtimeChannel.realtime_agent must reject cross-org agents
# ---------------------------------------------------------------------------


def _agent(org):
    return Agent.objects.create(role="r", goal="g", backstory="b", org=org)


def _realtime_agent(org):
    return RealtimeAgent.objects.create(agent=_agent(org))


@pytest.mark.django_db
def test_realtime_channel_rejects_cross_org_realtime_agent(auth_client, org_b):
    """Assigning an org-B RealtimeAgent to a channel created in default_org
    (auth_client's active org) must be rejected as an invalid pk, not leak
    the cross-org row's existence via a 403."""
    cross_org_agent = _realtime_agent(org_b)

    url = reverse("realtimechannel-list")
    resp = auth_client.post(
        url,
        {"name": "cross-org-channel", "realtime_agent": cross_org_agent.pk},
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "does not exist" in str(resp.data).lower()


@pytest.mark.django_db
def test_realtime_channel_accepts_same_org_realtime_agent(auth_client, default_org):
    same_org_agent = _realtime_agent(default_org)

    url = reverse("realtimechannel-list")
    resp = auth_client.post(
        url,
        {"name": "same-org-channel", "realtime_agent": same_org_agent.pk},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    channel = RealtimeChannel.objects.get(pk=resp.data["id"])
    assert channel.realtime_agent_id == same_org_agent.pk


# ---------------------------------------------------------------------------
# Nested RealtimeAgentWriteSerializer context propagation (EST-3629/3630
# follow-up) — AgentWriteSerializer nests RealtimeAgentWriteSerializer
# declaratively (no explicit context= passed at instantiation). Confirm DRF's
# implicit context propagation through the field tree actually works end to
# end for the org-scoped openai_config/elevenlabs_config/gemini_config
# fields, rather than silently deny-all'ing every pk.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_create_nested_realtime_agent_accepts_same_org_config(
    auth_client, default_org
):
    config = OpenAIRealtimeConfig.objects.create(org=default_org, custom_name="cfg")

    url = reverse("agent-list")
    resp = auth_client.post(
        url,
        {
            "role": "r",
            "goal": "g",
            "backstory": "b",
            "realtime_agent": {"openai_config": config.pk},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    agent = Agent.objects.get(pk=resp.data["id"])
    assert agent.realtime_agent.openai_config_id == config.pk


@pytest.mark.django_db
def test_agent_create_nested_realtime_agent_rejects_cross_org_config(
    auth_client, org_b
):
    cross_org_config = OpenAIRealtimeConfig.objects.create(
        org=org_b, custom_name="cfg"
    )

    url = reverse("agent-list")
    resp = auth_client.post(
        url,
        {
            "role": "r",
            "goal": "g",
            "backstory": "b",
            "realtime_agent": {"openai_config": cross_org_config.pk},
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "does not exist" in str(resp.data).lower()
