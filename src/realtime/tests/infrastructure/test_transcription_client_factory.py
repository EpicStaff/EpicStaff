from unittest.mock import AsyncMock

import pytest

from src.shared.models import RealtimeAgentChatData
from infrastructure.transcription.transcription_client_factory import (
    TranscriptionClientFactory,
)
from tests.conftest import TRANSPORT_CRYPTOGRAPHER, seal
from utils.transport_secrets import SecretDecryptionError

PLAINTEXT_TRANSCRIPT_API_KEY = "sk-transcript-plaintext"


def _make_config(**overrides) -> RealtimeAgentChatData:
    defaults = dict(
        connection_key="test_key",
        org_id=1,
        rt_api_key=seal("api_key"),
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
        transcript_api_key=seal(PLAINTEXT_TRANSCRIPT_API_KEY),
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

    client = TranscriptionClientFactory(TRANSPORT_CRYPTOGRAPHER).create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert (client.org_id, client.user_id, client.base_url) == (21, 55, expected_ws_url)


def test_elevenlabs_has_no_separate_transcription_client():
    config = _make_config(rt_provider="elevenlabs")

    assert TranscriptionClientFactory(TRANSPORT_CRYPTOGRAPHER).create(config=config, on_server_event=AsyncMock(), buffer=None) is None


def test_openai_transcription_client_gets_the_decrypted_api_key():
    client = TranscriptionClientFactory(TRANSPORT_CRYPTOGRAPHER).create(config=_make_config(), on_server_event=AsyncMock(), buffer=None)

    assert client.api_key == PLAINTEXT_TRANSCRIPT_API_KEY


def test_an_undecryptable_transcript_api_key_fails_naming_the_field_only():
    config = _make_config(transcript_api_key=PLAINTEXT_TRANSCRIPT_API_KEY)

    with pytest.raises(SecretDecryptionError) as failure:
        TranscriptionClientFactory(TRANSPORT_CRYPTOGRAPHER).create(config=config, on_server_event=AsyncMock(), buffer=None)

    assert str(failure.value) == "transcript_api_key could not be decrypted"
