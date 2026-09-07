"""PATCH/PUT `/api/realtime-agent-definitions/<pk>/`.

Regression coverage for a reported "update appears to succeed but the
provider config doesn't end up persisted" bug. Root cause investigation
(see RealtimeAgentDefinitionSerializer.validate()) found the serializer's
`agent_definition` field — the model's own primary key (a OneToOneField) —
was writable on update with no guard against it differing from the instance
being updated. Had a caller ever sent a mismatched `agent_definition`,
Django's `save()` would have attempted an UPDATE affecting 0 rows and
silently fallen back to an INSERT, orphaning a new row while leaving the
real target completely untouched — which looks exactly like a silent no-op.

These tests confirm:
- The exact reported payload shape (agent_definition matching the URL's own
  pk, one provider config set, the other two explicit null) persists
  correctly via both PATCH and PUT.
- A payload with an `agent_definition` different from the instance being
  updated is now rejected with 400, instead of silently doing nothing to
  the intended target.
"""

import pytest
from django.urls import reverse

from agents.models import AgentDefinition
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentDefinition
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def agent_definition(default_org, llm_config):
    return AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )


@pytest.fixture
def other_agent_definition(default_org, llm_config):
    return AgentDefinition.objects.create(
        organization=default_org,
        name="other-voice-agent",
        llm_config=llm_config,
    )


@pytest.fixture
def rt_agent_definition(agent_definition):
    return RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)


def _base_payload(rt_agent_definition, openai_config_id):
    return {
        "agent_definition": rt_agent_definition.pk,
        "openai_config": openai_config_id,
        "elevenlabs_config": None,
        "gemini_config": None,
        "wake_word": "Banana Lover",
        "stop_prompt": "stop",
        "language": None,
        "voice_recognition_prompt": None,
        "voice": "alloy",
    }


@pytest.mark.django_db
def test_patch_sets_new_provider_config(
    auth_client, rt_agent_definition, openai_realtime_provider_config
):
    url = reverse("realtimeagentdefinition-detail", args=[rt_agent_definition.pk])
    payload = _base_payload(rt_agent_definition, openai_realtime_provider_config.pk)

    resp = auth_client.patch(url, payload, format="json")

    assert resp.status_code == 200, resp.data
    rt_agent_definition.refresh_from_db()
    assert rt_agent_definition.openai_config_id == openai_realtime_provider_config.pk
    assert rt_agent_definition.wake_word == "Banana Lover"


@pytest.mark.django_db
def test_put_sets_new_provider_config(
    auth_client, rt_agent_definition, openai_realtime_provider_config
):
    url = reverse("realtimeagentdefinition-detail", args=[rt_agent_definition.pk])
    payload = _base_payload(rt_agent_definition, openai_realtime_provider_config.pk)

    resp = auth_client.put(url, payload, format="json")

    assert resp.status_code == 200, resp.data
    rt_agent_definition.refresh_from_db()
    assert rt_agent_definition.openai_config_id == openai_realtime_provider_config.pk
    assert rt_agent_definition.wake_word == "Banana Lover"


@pytest.mark.django_db
def test_patch_with_mismatched_agent_definition_rejected(
    auth_client,
    rt_agent_definition,
    other_agent_definition,
    openai_realtime_provider_config,
):
    """A payload whose `agent_definition` doesn't match the instance being
    updated (URL pk) must be rejected explicitly, not silently no-op or
    orphan-insert a new row under `other_agent_definition`."""
    url = reverse("realtimeagentdefinition-detail", args=[rt_agent_definition.pk])
    payload = _base_payload(rt_agent_definition, openai_realtime_provider_config.pk)
    payload["agent_definition"] = other_agent_definition.pk

    resp = auth_client.patch(url, payload, format="json")

    assert resp.status_code == 400, resp.data
    assert "agent_definition" in str(resp.data)

    rt_agent_definition.refresh_from_db()
    assert rt_agent_definition.openai_config_id is None
    assert not RealtimeAgentDefinition.objects.filter(
        agent_definition=other_agent_definition
    ).exists()
