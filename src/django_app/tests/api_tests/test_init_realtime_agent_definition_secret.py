"""Regression guard for secret resolution on the AgentDefinition realtime path.

The `agent_id` path resolves `rt_api_key_secret_id` -> plaintext through
`SecretResolver` before publishing to `realtime_agents:schema`. The
`agent_definition_id` path must behave identically: same carrier fields, same
org-scoped resolution. Merging `main` (which still read the removed plaintext
`RealtimeConfig.api_key` column) into the secrets branch broke exactly this
path, so both halves are pinned here — the key reaches the payload, and it can
only come from the agent's own realtime config.

`config` is a client-supplied `DictField`. Naming a Secret in it
(`rt_api_key_secret_id`) is ignored, whether the Secret belongs to another
organization or to the caller's own: the key a session uses is the one its
agent's realtime config names, which is what run admission checks.
"""

import json

import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentDefinition
from tables.services.secrets import secret_service
from tests.fixtures import *  # noqa: F401,F403

FOREIGN_PLAINTEXT = "sk-FOREIGN-must-never-be-decrypted-9c02"
REALTIME_PLAINTEXT = "sk-rt-definition-realtime-key"
TRANSCRIPTION_PLAINTEXT = "sk-rt-definition-transcription-key"


@pytest.fixture
def default_org_client(regular_user, default_org):
    # JWT auth is inert under tests/settings.py; force_authenticate is the only
    # pattern that produces a real user here.
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def openai_config(default_org):
    # Distinct plaintexts, so the payload proves each key came from its own secret.
    return OpenAIRealtimeConfig.objects.create(
        custom_name="rt-definition-openai-config",
        api_key_secret=secret_service.create(
            text=REALTIME_PLAINTEXT, org=default_org, name="rt-definition-key"
        ),
        transcription_api_key_secret=secret_service.create(
            text=TRANSCRIPTION_PLAINTEXT,
            org=default_org,
            name="rt-definition-transcription-key",
        ),
        org=default_org,
    )


@pytest.fixture
def rt_agent_definition(default_org, llm_config, openai_config):
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be concise and helpful"}],
        llm_config=llm_config,
    )
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
        openai_config=openai_config,
    )


def _published_payload(redis_client_mock) -> dict:
    channel, body = redis_client_mock.publish.call_args[0]
    assert channel == "realtime_agents:schema"
    return json.loads(body)


@pytest.mark.django_db
def test_agent_definition_realtime_keys_are_resolved_to_plaintext(
    default_org_client, rt_agent_definition, redis_client_mock
):
    resp = default_org_client.post(
        "/api/init-realtime/",
        {"agent_definition_id": rt_agent_definition.pk},
        format="json",
    )

    assert resp.status_code == 201, resp.data

    payload = _published_payload(redis_client_mock)
    # Plaintext values come from the `openai_config` fixture secrets.
    assert payload["rt_api_key"] == REALTIME_PLAINTEXT
    assert payload["transcript_api_key"] == TRANSCRIPTION_PLAINTEXT
    # Carriers are `exclude=True` — the id must never ride along to the consumer.
    assert "rt_api_key_secret_id" not in payload
    assert "transcript_api_key_secret_id" not in payload


@pytest.mark.django_db
def test_agent_definition_config_cannot_name_another_orgs_secret(
    default_org_client, rt_agent_definition, redis_client_mock
):
    foreign_org = Organization.objects.create(name="Org Foreign RT Definition")
    foreign_secret = secret_service.create(
        text=FOREIGN_PLAINTEXT, org=foreign_org, name="foreign-rt-definition-key"
    )

    resp = default_org_client.post(
        "/api/init-realtime/",
        {
            "agent_definition_id": rt_agent_definition.pk,
            "config": {"rt_api_key_secret_id": foreign_secret.pk},
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    payload = _published_payload(redis_client_mock)
    assert payload["rt_api_key"] == REALTIME_PLAINTEXT
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert FOREIGN_PLAINTEXT not in published


@pytest.mark.django_db
def test_agent_definition_config_cannot_swap_in_another_secret_of_the_org(
    default_org_client, rt_agent_definition, default_org, redis_client_mock
):
    own_secret = secret_service.create(
        text="sk-own-rt-definition-key", org=default_org, name="own-rt-definition-key"
    )

    resp = default_org_client.post(
        "/api/init-realtime/",
        {
            "agent_definition_id": rt_agent_definition.pk,
            "config": {"rt_api_key_secret_id": own_secret.pk},
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    payload = _published_payload(redis_client_mock)
    assert payload["rt_api_key"] == REALTIME_PLAINTEXT
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert "sk-own-rt-definition-key" not in published


@pytest.fixture
def member_client(default_org, django_user_model):
    """A Member of the organization: may start realtime sessions, holds no `secrets: use`."""
    member = django_user_model.objects.create_user(
        email="rt-definition-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(
        user=member,
        org=default_org,
        role=Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True),
    )
    client = APIClient()
    client.force_authenticate(user=member)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.mark.django_db
def test_a_member_without_secrets_use_cannot_send_an_org_secret_through_the_config(
    member_client, rt_agent_definition, default_org, redis_client_mock
):
    org_secret = secret_service.create(
        text="sk-org-secret-the-member-may-not-use", org=default_org, name="payments-key"
    )

    resp = member_client.post(
        "/api/init-realtime/",
        {
            "agent_definition_id": rt_agent_definition.pk,
            "config": {"rt_api_key_secret_id": org_secret.pk},
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    assert _published_payload(redis_client_mock)["rt_api_key"] == REALTIME_PLAINTEXT
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert "sk-org-secret-the-member-may-not-use" not in published
