import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import WebSocket, WebSocketDisconnect
from src.shared.models import RealtimeAgentChatData
from domain.models.chat_mode import ChatMode
from domain.ports.i_summarization_client import ISummarizationClient
from domain.ports.i_transcription_client_factory import ITranscriptionClientFactory
from domain.services.chat_buffer import ChatSummarizedBuffer
from domain.services.summarize_buffer import ChatSummarizedBufferClient
from application.conversation_service import ConversationService
from application.tool_manager_service import ToolManagerService
from infrastructure.providers.factory import RealtimeAgentClientFactory
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL


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


# ---------------------------------------------------------------------------
# execute — a failing process_message never leaks exception text to the client
# ---------------------------------------------------------------------------


async def _run_until_disconnect(service) -> None:
    """Drive execute() through one client message that the provider fails to process."""

    async def provider_loop():
        await asyncio.Event().wait()

    rt_agent_client = AsyncMock()
    rt_agent_client.handle_messages = provider_loop
    rt_agent_client.process_message = AsyncMock(
        side_effect=RuntimeError(f"upstream rejected api_key={SECRET_SENTINEL}")
    )
    service.factory.create.return_value = rt_agent_client
    service.transcription_client_factory.create.return_value = None
    service.client_websocket.scope = {"subprotocols": []}
    service.client_websocket.receive_json = AsyncMock(
        side_effect=[{"type": "conversation.item.create"}, WebSocketDisconnect()]
    )

    await service.execute()


def _error_payloads(service) -> list[dict]:
    return [
        call.args[0]
        for call in service.client_websocket.send_json.await_args_list
        if call.args[0].get("type") == "error"
    ]


@pytest.mark.asyncio
async def test_process_message_failure_sends_fixed_error_without_exception_text(service):
    await _run_until_disconnect(service)

    error_payloads = _error_payloads(service)
    assert len(error_payloads) == 1
    assert error_payloads[0]["message"].startswith("Failed to process the message")
    assert PUBLIC_ERROR_REFERENCE.search(error_payloads[0]["message"])
    for call in service.client_websocket.send_json.await_args_list:
        assert SECRET_SENTINEL not in str(call.args[0])


@pytest.mark.asyncio
async def test_process_message_failure_logs_detail_under_the_sent_correlation_id(
    service, captured_log_messages
):
    await _run_until_disconnect(service)

    message = _error_payloads(service)[0]["message"]
    correlation_id = PUBLIC_ERROR_REFERENCE.search(message).group(1)
    matching_logs = [log for log in captured_log_messages if correlation_id in log]
    assert len(matching_logs) == 1
    assert SECRET_SENTINEL in matching_logs[0]


def test_maybe_create_transcription_delegates_to_factory(service, mock_tool_manager):
    mock_factory = MagicMock(spec=ITranscriptionClientFactory)
    service.transcription_client_factory = mock_factory
    mock_buffer = MagicMock(spec=ChatSummarizedBuffer)

    service._maybe_create_transcription_client(mock_buffer)

    mock_factory.create.assert_called_once()
    call_kwargs = mock_factory.create.call_args[1]
    assert call_kwargs["config"] is service.realtime_agent_chat_data
    assert call_kwargs["buffer"] is mock_buffer
