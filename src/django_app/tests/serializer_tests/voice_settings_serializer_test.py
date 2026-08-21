"""
Serializer tests for VoiceSettingsSerializer's handling of the legacy
`voice_agent` (RealtimeAgent) field alongside the authoritative
`voice_agent_definition` (RealtimeAgentDefinition) field.

`voice_agent` is read-only: existing consumers can still read it, but no
write may set, clear, or otherwise change it through this serializer.
`voice_agent_definition` is the only writable FK, and setting it is always
valid regardless of any legacy `voice_agent` value already on the instance.
"""

import pytest

from agents.models import AgentDefinition
from tables.models.realtime_models import RealtimeAgent, RealtimeAgentDefinition
from tables.models.webhook_models import VoiceSettings
from tables.serializers.model_serializers.webhook_serializers import (
    VoiceSettingsSerializer,
)
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def rt_agent(
    wikipedia_agent, openai_realtime_model_config, realtime_transcription_config
):
    return RealtimeAgent.objects.create(
        agent=wikipedia_agent,
        realtime_config=openai_realtime_model_config,
        realtime_transcription_config=realtime_transcription_config,
    )


@pytest.fixture
def rt_agent_definition(
    default_org, llm_config, openai_realtime_model_config, realtime_transcription_config
):
    agent_definition = AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent-definition",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
        realtime_config=openai_realtime_model_config,
        realtime_transcription_config=realtime_transcription_config,
    )


@pytest.mark.django_db
def test_voice_agent_definition_alone_is_valid(rt_agent_definition):
    serializer = VoiceSettingsSerializer(
        data={"voice_agent_definition": rt_agent_definition.pk}
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_voice_agent_in_write_payload_is_ignored(rt_agent):
    serializer = VoiceSettingsSerializer(data={"voice_agent": rt_agent.pk})

    assert serializer.is_valid(), serializer.errors
    instance = serializer.save()

    assert instance.voice_agent is None


@pytest.mark.django_db
def test_setting_voice_agent_definition_when_legacy_voice_agent_already_set_is_valid(
    rt_agent, rt_agent_definition
):
    # Legacy voice_agent set directly on the model, bypassing the serializer —
    # simulates data left over from before voice_agent became read-only.
    instance = VoiceSettings.objects.create(pk=1, voice_agent=rt_agent)

    serializer = VoiceSettingsSerializer(
        instance=instance,
        data={"voice_agent_definition": rt_agent_definition.pk},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    saved = serializer.save()
    assert saved.voice_agent_definition_id == rt_agent_definition.pk
    # The read-only legacy field is left untouched by the write.
    assert saved.voice_agent_id == rt_agent.pk


@pytest.mark.django_db
def test_voice_agent_remains_readable_after_legacy_assignment(rt_agent):
    instance = VoiceSettings.objects.create(pk=1, voice_agent=rt_agent)

    serializer = VoiceSettingsSerializer(instance=instance)

    assert serializer.data["voice_agent"] == rt_agent.pk


@pytest.mark.django_db
def test_write_cannot_clear_legacy_voice_agent(rt_agent):
    instance = VoiceSettings.objects.create(pk=1, voice_agent=rt_agent)

    serializer = VoiceSettingsSerializer(
        instance=instance,
        data={"voice_agent": None},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    saved = serializer.save()

    assert saved.voice_agent_id == rt_agent.pk
