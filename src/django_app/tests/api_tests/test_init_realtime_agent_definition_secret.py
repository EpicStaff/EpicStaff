"""Regression guard for secret resolution on the AgentDefinition realtime path.

The `agent_id` path resolves `rt_api_key_secret_id` -> plaintext through
`SecretResolver` before publishing to `realtime_agents:schema`. The
`agent_definition_id` path must behave identically: same carrier fields, same
org-scoped resolution. Merging `main` (which still read the removed plaintext
`RealtimeConfig.api_key` column) into the secrets branch broke exactly this
path, so both halves are pinned here — the key reaches the payload, and it can
only come from the caller's own org.

`config` is an unconstrained `DictField` and `RealtimeService.init_realtime_agent_definition`
setattrs every key that exists on the payload, so `rt_api_key_secret_id` is a
declared carrier a caller can override directly in the request body.
`test_agent_definition_config_cannot_name_another_orgs_secret` proves a
foreign org's secret id is rejected; `test_agent_definition_config_with_own_orgs_secret_still_works`
is the matching positive control -- proving the theft is blocked is worthless
if the legitimate override (a caller pointing at one of their own org's other
secrets) broke along with it.
"""

import json

import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from tables.models.rbac_models import Organization
from tables.models.realtime_models import RealtimeAgentDefinition
from tables.services.secrets import secret_service
from tests.fixtures import *  # noqa: F401,F403

FOREIGN_PLAINTEXT = "sk-FOREIGN-must-never-be-decrypted-9c02"


@pytest.fixture
def default_org_client(regular_user, default_org):
    # JWT auth is inert under tests/settings.py; force_authenticate is the only
    # pattern that produces a real user here.
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def rt_agent_definition(
    default_org, llm_config, openai_realtime_model_config, realtime_transcription_config
):
    agent_definition = AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
        realtime_config=openai_realtime_model_config,
        realtime_transcription_config=realtime_transcription_config,
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
    # Plaintext values come from the `openai_realtime_model_config` /
    # `realtime_transcription_config` fixture secrets.
    assert payload["rt_api_key"] == "test"
    assert payload["transcript_api_key"] == "mock key"
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

    # Pin the cause to SecretResolver's org filter, not some unrelated failure.
    assert resp.status_code == 400, resp.data
    assert "could not be resolved" in resp.data["error"]
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert FOREIGN_PLAINTEXT not in published


@pytest.mark.django_db
def test_agent_definition_config_with_own_orgs_secret_still_works(
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
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert "sk-own-rt-definition-key" in published
