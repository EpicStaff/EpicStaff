import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import WebSocket
from src.shared.models import RealtimeAgentChatData
from domain.models.chat_mode import ChatMode
from domain.ports.i_summarization_client import ISummarizationClient
from domain.ports.i_transcription_client_factory import ITranscriptionClientFactory
from domain.services.chat_buffer import ChatSummarizedBuffer
from domain.services.summarize_buffer import ChatSummarizedBufferClient
from application.conversation_service import ConversationService
from application.tool_manager_service import ToolManagerService
from infrastructure.providers.factory import RealtimeAgentClientFactory


def _make_chat_data(rt_provider: str = "openai") -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key="test_key",
        org_id=1,
        rt_api_key="api_key",
        rt_model_name="gpt-4o",
        rt_provider=rt_provider,
        wake_word="hey agent",
        voice="alloy",
        temperature=0.7,
        language="en",
        goal="help",
        backstory="assistant",
        role="assistant",
        knowledge_collection_id=None,
        memory=False,
        stop_prompt="stop now",
        voice_recognition_prompt=None,
        tools=[],
        llm=None,
    )


@pytest.fixture
def mock_tool_manager():
    tm = MagicMock(spec=ToolManagerService)
    tm.register_tools_from_rt_agent_chat_data = MagicMock()
    return tm


@pytest.fixture
def service(mock_tool_manager):
    return ConversationService(
        client_websocket=AsyncMock(spec=WebSocket),
        realtime_agent_chat_data=_make_chat_data(),
        instructions="Be helpful.",
        tool_manager_service=mock_tool_manager,
        connections={},
        factory=MagicMock(spec=RealtimeAgentClientFactory),
        summ_client=MagicMock(spec=ISummarizationClient),
        transcription_client_factory=MagicMock(spec=ITranscriptionClientFactory),
    )


# ---------------------------------------------------------------------------
# IChatModeController
# ---------------------------------------------------------------------------


def test_default_chat_mode_is_conversation(service):
    assert service.current_chat_mode == ChatMode.CONVERSATION


def test_set_chat_mode_listen(service):
    service.set_chat_mode(ChatMode.LISTEN)
    assert service.current_chat_mode == ChatMode.LISTEN


def test_set_chat_mode_back_to_conversation(service):
    service.set_chat_mode(ChatMode.LISTEN)
    service.set_chat_mode(ChatMode.CONVERSATION)
    assert service.current_chat_mode == ChatMode.CONVERSATION


# ---------------------------------------------------------------------------
# Constructor registers tools
# ---------------------------------------------------------------------------


def test_constructor_registers_tools(mock_tool_manager):
    ConversationService(
        client_websocket=AsyncMock(spec=WebSocket),
        realtime_agent_chat_data=_make_chat_data(),
        instructions="hi",
        tool_manager_service=mock_tool_manager,
        connections={},
        factory=MagicMock(spec=RealtimeAgentClientFactory),
        summ_client=MagicMock(spec=ISummarizationClient),
        transcription_client_factory=MagicMock(spec=ITranscriptionClientFactory),
    )
    mock_tool_manager.register_tools_from_rt_agent_chat_data.assert_called_once()


def test_elevenlabs_passes_none_as_chat_mode_controller(mock_tool_manager):
    """ElevenLabs has built-in VAD — StopAgent tool is disabled (controller=None)."""
    ConversationService(
        client_websocket=AsyncMock(spec=WebSocket),
        realtime_agent_chat_data=_make_chat_data(rt_provider="elevenlabs"),
        instructions="hi",
        tool_manager_service=mock_tool_manager,
        connections={},
        factory=MagicMock(spec=RealtimeAgentClientFactory),
        summ_client=MagicMock(spec=ISummarizationClient),
        transcription_client_factory=MagicMock(spec=ITranscriptionClientFactory),
    )
    _, kwargs = mock_tool_manager.register_tools_from_rt_agent_chat_data.call_args
    assert kwargs["chat_mode_controller"] is None


def test_openai_passes_self_as_chat_mode_controller(mock_tool_manager):
    svc = ConversationService(
        client_websocket=AsyncMock(spec=WebSocket),
        realtime_agent_chat_data=_make_chat_data(rt_provider="openai"),
        instructions="hi",
        tool_manager_service=mock_tool_manager,
        connections={},
        factory=MagicMock(spec=RealtimeAgentClientFactory),
        summ_client=MagicMock(spec=ISummarizationClient),
        transcription_client_factory=MagicMock(spec=ITranscriptionClientFactory),
    )
    _, kwargs = mock_tool_manager.register_tools_from_rt_agent_chat_data.call_args
    assert kwargs["chat_mode_controller"] is svc


# ---------------------------------------------------------------------------
# _initialize_buffer
# ---------------------------------------------------------------------------


def test_initialize_buffer_returns_correct_types(service):
    buffer, summ_client = service._initialize_buffer(
        max_buffer_tokens=2000, max_chunks_tokens=4000
    )
    assert isinstance(buffer, ChatSummarizedBuffer)
    assert isinstance(summ_client, ChatSummarizedBufferClient)


def test_initialize_buffer_custom_token_limits(service):
    buffer, _ = service._initialize_buffer(
        max_buffer_tokens=500, max_chunks_tokens=1000
    )
    assert buffer._max_buffer_tokens == 500
    assert buffer._max_chunks_tokens == 1000


# ---------------------------------------------------------------------------
# _maybe_create_transcription_client
# ---------------------------------------------------------------------------


def test_maybe_create_transcription_delegates_to_factory(service, mock_tool_manager):
    mock_factory = MagicMock(spec=ITranscriptionClientFactory)
    service.transcription_client_factory = mock_factory
    mock_buffer = MagicMock(spec=ChatSummarizedBuffer)

    service._maybe_create_transcription_client(mock_buffer)

    mock_factory.create.assert_called_once()
    call_kwargs = mock_factory.create.call_args[1]
    assert call_kwargs["config"] is service.realtime_agent_chat_data
    assert call_kwargs["buffer"] is mock_buffer
