from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.parametrize(
    ("rt_base_url", "expected_ws_url"),
    [(None, "wss://api.openai.com/v1/realtime"), ("https://my-proxy.internal", "wss://my-proxy.internal/v1/realtime")],
    ids=["default", "org-proxy"],
)
def test_openai_transcription_client_carries_caller_identity_and_endpoint(rt_base_url, expected_ws_url):
    config = _make_config(rt_provider="openai", org_id=21, user_id=55, rt_base_url=rt_base_url)

    client = TranscriptionClientFactory().create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert (client.org_id, client.user_id, client.base_url) == (21, 55, expected_ws_url)


def test_elevenlabs_has_no_separate_transcription_client():
    config = _make_config(rt_provider="elevenlabs")

    assert TranscriptionClientFactory().create(config=config, on_server_event=AsyncMock(), buffer=None) is None
