"""RealtimeAgentClientFactory picks the provider adapter and configures it.

The real adapters are built (constructing one does not connect); only Gemini's
SDK client, an external API, is patched.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
)
from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from infrastructure.providers.factory import RealtimeAgentClientFactory
from infrastructure.providers.gemini.gemini_realtime_agent_client import GeminiRealtimeAgentClient
from infrastructure.providers.openai.openai_realtime_agent_client import OpenaiRealtimeAgentClient
from src.shared.models import RealtimeAgentChatData


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
    )
    defaults.update(overrides)
    return RealtimeAgentChatData(**defaults)


@pytest.fixture(autouse=True)
def gemini_sdk():
    with patch("infrastructure.providers.gemini.gemini_realtime_agent_client.genai"):
        yield


def _create(config: RealtimeAgentChatData, is_twilio: bool = False):
    factory = RealtimeAgentClientFactory(elevenlabs_agent_provisioner=MagicMock(spec=ElevenLabsAgentProvisioner))
    return factory.create(
        config=config,
        rt_tools=[],
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=AsyncMock(),
        is_twilio=is_twilio,
    )


@pytest.mark.parametrize(
    ("provider", "expected_class"),
    [
        ("openai", OpenaiRealtimeAgentClient),
        ("unknown_provider", OpenaiRealtimeAgentClient),
        ("elevenlabs", ElevenLabsRealtimeAgentClient),
        ("gemini", GeminiRealtimeAgentClient),
    ],
)
@pytest.mark.parametrize("is_twilio", [True, False], ids=["twilio", "browser"])
def test_provider_selects_the_adapter_and_carries_caller_identity(provider, expected_class, is_twilio):
    client = _create(_make_config(rt_provider=provider, org_id=7, user_id=101), is_twilio=is_twilio)

    assert type(client) is expected_class
    # Tools run org-scoped calls on behalf of this caller.
    assert (client.org_id, client.user_id) == (7, 101)
    assert client.is_twilio is is_twilio


@pytest.mark.parametrize(
    ("is_twilio", "expected_format"), [(True, "g711_ulaw"), (False, "pcm16")], ids=["twilio", "browser"]
)
def test_openai_audio_format_is_forced_to_mulaw_for_twilio(is_twilio, expected_format):
    client = _create(_make_config(input_audio_format="pcm16", output_audio_format="pcm16"), is_twilio=is_twilio)

    assert (client.input_audio_format, client.output_audio_format) == (expected_format, expected_format)


@pytest.mark.parametrize(
    ("rt_base_url", "expected_ws_url"),
    [("https://my-proxy.internal", "wss://my-proxy.internal/v1/realtime"), (None, "wss://api.openai.com/v1/realtime")],
    ids=["proxy", "default"],
)
def test_openai_connects_to_the_configured_base_url(rt_base_url, expected_ws_url):
    assert _create(_make_config(rt_base_url=rt_base_url)).base_url == expected_ws_url


def test_elevenlabs_gets_its_agent_definition_and_default_llm():
    client = _create(_make_config(rt_provider="elevenlabs", rt_agent_definition_id=17))

    assert client.rt_agent_definition_id == 17
    assert client.llm_model == "gemini-2.5-flash"


def test_gemini_gets_the_configured_model():
    client = _create(_make_config(rt_provider="gemini", rt_model_name="gemini-3.1-flash-live-preview"))

    assert client.model == "gemini-3.1-flash-live-preview"
