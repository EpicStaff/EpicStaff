"""
Serializer tests for VoiceSettingsSerializer's mutual-exclusivity validation
between `voice_agent` (legacy RealtimeAgent) and `voice_agent_definition`
(RealtimeAgentDefinition).
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
def test_both_fks_set_returns_validation_error(rt_agent, rt_agent_definition):
    serializer = VoiceSettingsSerializer(
        data={
            "voice_agent": rt_agent.pk,
            "voice_agent_definition": rt_agent_definition.pk,
        }
    )

    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


@pytest.mark.django_db
def test_only_voice_agent_definition_set_is_valid(rt_agent_definition):
    serializer = VoiceSettingsSerializer(
        data={"voice_agent_definition": rt_agent_definition.pk}
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_only_voice_agent_set_is_valid(rt_agent):
    serializer = VoiceSettingsSerializer(data={"voice_agent": rt_agent.pk})

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_patch_setting_voice_agent_definition_when_voice_agent_already_set_returns_error(
    rt_agent, rt_agent_definition
):
    instance = VoiceSettings.objects.create(pk=1, voice_agent=rt_agent)

    serializer = VoiceSettingsSerializer(
        instance=instance,
        data={"voice_agent_definition": rt_agent_definition.pk},
        partial=True,
    )

    assert not serializer.is_valid()
    assert "non_field_errors" in serializer.errors


@pytest.mark.django_db
def test_patch_clearing_voice_agent_while_setting_voice_agent_definition_is_valid(
    rt_agent, rt_agent_definition
):
    instance = VoiceSettings.objects.create(pk=1, voice_agent=rt_agent)

    serializer = VoiceSettingsSerializer(
        instance=instance,
        data={"voice_agent": None, "voice_agent_definition": rt_agent_definition.pk},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
