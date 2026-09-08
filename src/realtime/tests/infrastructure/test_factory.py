import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.shared.models import RealtimeAgentChatData
from infrastructure.providers.factory import RealtimeAgentClientFactory
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
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
    )
    defaults.update(overrides)
    return RealtimeAgentChatData(**defaults)


@pytest.fixture
def provisioner():
    return MagicMock(spec=ElevenLabsAgentProvisioner)


@pytest.fixture
def factory(provisioner):
    return RealtimeAgentClientFactory(elevenlabs_agent_provisioner=provisioner)


@pytest.fixture
def on_server_event():
    return AsyncMock()


@pytest.fixture
def rt_tools():
    return []


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_create_openai_by_default(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    MockOpenai.assert_called_once()


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_create_openai_when_unknown_provider(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="unknown_provider")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    MockOpenai.assert_called_once()


@patch("infrastructure.providers.factory.ElevenLabsRealtimeAgentClient")
def test_create_elevenlabs_when_provider_elevenlabs(
    MockElevenLabs, factory, rt_tools, on_server_event
):
    config = _make_config(rt_provider="elevenlabs")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    MockElevenLabs.assert_called_once()


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_twilio_forces_g711_ulaw(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai", input_audio_format="pcm16", output_audio_format="pcm16")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=True,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("input_audio_format") == "g711_ulaw"
    assert kwargs.get("output_audio_format") == "g711_ulaw"


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_passes_org_id(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai", org_id=7)
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("org_id") == 7


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_passes_rt_base_url(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai", rt_base_url="https://my-proxy.internal")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("base_url") == "https://my-proxy.internal"


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_passes_none_rt_base_url_by_default(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("base_url") is None


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_passes_user_id(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="openai", user_id=101)
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("user_id") == 101


@patch("infrastructure.providers.factory.OpenaiRealtimeAgentClient")
def test_openai_non_twilio_uses_config_format(MockOpenai, factory, rt_tools, on_server_event):
    config = _make_config(input_audio_format="pcm16", output_audio_format="pcm16")
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=False,
    )
    _, kwargs = MockOpenai.call_args
    assert kwargs.get("input_audio_format") == "pcm16"
    assert kwargs.get("output_audio_format") == "pcm16"


@patch("infrastructure.providers.factory.ElevenLabsRealtimeAgentClient")
def test_elevenlabs_passes_org_id(MockElevenLabs, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="elevenlabs", org_id=9)
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockElevenLabs.call_args
    assert kwargs.get("org_id") == 9


@patch("infrastructure.providers.factory.ElevenLabsRealtimeAgentClient")
def test_elevenlabs_passes_user_id(MockElevenLabs, factory, rt_tools, on_server_event):
    config = _make_config(rt_provider="elevenlabs", user_id=102)
    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    _, kwargs = MockElevenLabs.call_args
    assert kwargs.get("user_id") == 102


@patch("infrastructure.providers.factory.ElevenLabsRealtimeAgentClient")
def test_elevenlabs_twilio_sets_is_twilio_flag(
    MockElevenLabs, factory, rt_tools, on_server_event
):
    config = _make_config(rt_provider="elevenlabs")
    client_mock = MagicMock()
    MockElevenLabs.return_value = client_mock

    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=True,
    )
    assert client_mock.is_twilio is True


@patch("infrastructure.providers.factory.ElevenLabsRealtimeAgentClient")
def test_elevenlabs_non_twilio_is_twilio_false(
    MockElevenLabs, factory, rt_tools, on_server_event
):
    config = _make_config(rt_provider="elevenlabs")
    client_mock = MagicMock()
    MockElevenLabs.return_value = client_mock

    factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=False,
    )
    assert client_mock.is_twilio is False


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

_GEMINI_GENAI = "infrastructure.providers.gemini.gemini_realtime_agent_client.genai"


@patch(_GEMINI_GENAI)
def test_create_gemini_when_provider_gemini(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini", rt_model_name="gemini-2.0-flash-live-001")
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    assert type(result).__name__ == "GeminiRealtimeAgentClient"


@patch(_GEMINI_GENAI)
def test_gemini_twilio_sets_is_twilio_flag(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini")
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=True,
    )
    assert result.is_twilio is True


@patch(_GEMINI_GENAI)
def test_gemini_non_twilio_is_twilio_false(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini")
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
        is_twilio=False,
    )
    assert result.is_twilio is False


@patch(_GEMINI_GENAI)
def test_gemini_passes_org_id(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini", org_id=13)
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    assert result.org_id == 13


@patch(_GEMINI_GENAI)
def test_gemini_passes_user_id(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini", user_id=103)
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    assert result.user_id == 103


@patch(_GEMINI_GENAI)
def test_gemini_passes_model_name(mock_genai, factory, rt_tools, on_server_event):
    mock_genai.Client.return_value = MagicMock()
    config = _make_config(rt_provider="gemini", rt_model_name="gemini-3.1-flash-live-preview")
    result = factory.create(
        config=config,
        rt_tools=rt_tools,
        instructions="hi",
        tool_manager_service=MagicMock(),
        on_server_event=on_server_event,
    )
    assert result.model == "gemini-3.1-flash-live-preview"
