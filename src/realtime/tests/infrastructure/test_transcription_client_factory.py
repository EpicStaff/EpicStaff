from unittest.mock import AsyncMock

from src.shared.models import RealtimeAgentChatData
from infrastructure.transcription.transcription_client_factory import (
    TranscriptionClientFactory,
)


def _make_config(**overrides) -> RealtimeAgentChatData:
    defaults = dict(
        connection_key="test_key",
        org_id=1,
        rt_api_key="api_key",
        rt_model_name="gpt-4o-realtime-preview",
        rt_provider="openai",
        wake_word=None,
        voice="alloy",
        temperature=0.7,
        language="en",
        goal="help",
        backstory="assistant",
        role="assistant",
        knowledge_collection_id=None,
        memory=False,
        stop_prompt=None,
        voice_recognition_prompt=None,
        input_audio_format="pcm16",
        output_audio_format="pcm16",
        tools=[],
        llm=None,
        transcript_api_key="transcript_api_key",
    )
    defaults.update(overrides)
    return RealtimeAgentChatData(**defaults)


def test_openai_transcription_client_carries_org_id():
    factory = TranscriptionClientFactory()
    config = _make_config(rt_provider="openai", org_id=21)

    client = factory.create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert client is not None
    assert client.org_id == 21


def test_openai_transcription_client_carries_user_id():
    factory = TranscriptionClientFactory()
    config = _make_config(rt_provider="openai", user_id=55)

    client = factory.create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert client is not None
    assert client.user_id == 55


def test_elevenlabs_provider_returns_none_regardless_of_org_id():
    factory = TranscriptionClientFactory()
    config = _make_config(rt_provider="elevenlabs", org_id=21)

    client = factory.create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert client is None
