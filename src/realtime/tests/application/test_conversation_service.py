import asyncio
from typing import NamedTuple

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


def _make_chat_data(
    rt_provider: str = "openai", wake_word: str | None = "hey agent"
) -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key="test_key",
        org_id=1,
        rt_api_key="api_key",
        rt_model_name="gpt-4o",
        rt_provider=rt_provider,
        wake_word=wake_word,
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
def make_service(mock_tool_manager):
    def _make(
        wake_word: str | None = "hey agent", rt_provider: str = "openai"
    ) -> ConversationService:
        return ConversationService(
            client_websocket=AsyncMock(spec=WebSocket),
            realtime_agent_chat_data=_make_chat_data(
                rt_provider=rt_provider, wake_word=wake_word
            ),
            instructions="Be helpful.",
            tool_manager_service=mock_tool_manager,
            connections={},
            factory=MagicMock(spec=RealtimeAgentClientFactory),
            summ_client=MagicMock(spec=ISummarizationClient),
            transcription_client_factory=MagicMock(spec=ITranscriptionClientFactory),
        )

    return _make


@pytest.fixture
def service(make_service):
    return make_service()


# ---------------------------------------------------------------------------
# Wake-word gate — initial chat mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wake_word, expected_mode",
    [
        ("hey agent", ChatMode.LISTEN),
        ("Agent!", ChatMode.LISTEN),
        ("", ChatMode.CONVERSATION),
        ("   ", ChatMode.CONVERSATION),
        (None, ChatMode.CONVERSATION),
    ],
)
def test_initial_chat_mode_follows_wake_word(make_service, wake_word, expected_mode):
    assert make_service(wake_word=wake_word).current_chat_mode == expected_mode


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


# ---------------------------------------------------------------------------
# execute — wake-word gate
# ---------------------------------------------------------------------------


async def _idle_loop():
    await asyncio.Event().wait()


class ExecutedClients(NamedTuple):
    """The two mocked clients execute() can route a client message to."""

    rt_agent_client: AsyncMock
    transcription_client: AsyncMock


async def _run_execute_with_transcription(
    service, transcribed_text: str, prime_buffer=None
) -> ExecutedClients:
    """Drive execute() through one loop turn with `transcribed_text` already buffered.

    `prime_buffer`, if given, runs first with the real buffer — e.g. to simulate
    text transcribed (or a mode change) before the turn under test.

    Returns both mocked clients so the caller can assert which one received the
    audio message and whether the handover to the agent happened.
    """
    rt_agent_client = AsyncMock()
    rt_agent_client.handle_messages = _idle_loop
    rt_agent_client.process_message = AsyncMock(return_value=None)
    service.factory.create.return_value = rt_agent_client

    transcription_client = AsyncMock()
    transcription_client.handle_messages = _idle_loop
    transcription_client.process_message = AsyncMock(return_value=None)

    def create_transcription_client(config, on_server_event, buffer):
        if prime_buffer is not None:
            prime_buffer(buffer)
        buffer.append(transcribed_text)
        return transcription_client

    service.transcription_client_factory.create.side_effect = create_transcription_client
    service.client_websocket.scope = {"subprotocols": []}
    service.client_websocket.receive_json = AsyncMock(
        side_effect=[{"type": "input_audio_buffer.append"}, WebSocketDisconnect()]
    )

    await service.execute()
    return ExecutedClients(
        rt_agent_client=rt_agent_client, transcription_client=transcription_client
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("wake_word", ["hey agent", "Agent!"])
async def test_wake_word_in_transcript_hands_over_to_conversation(make_service, wake_word):
    service = make_service(wake_word=wake_word)

    clients = await _run_execute_with_transcription(service, "ok agent, what time is it")

    assert service.current_chat_mode == ChatMode.CONVERSATION
    clients.rt_agent_client.send_conversation_item_to_server.assert_awaited_once()
    clients.rt_agent_client.request_response.assert_awaited_once()
    # The handover turn itself is still transcribed — the agent takes over from the next turn.
    clients.transcription_client.process_message.assert_awaited()


@pytest.mark.asyncio
async def test_stop_then_wake_word_does_not_replay_earlier_turn(make_service):
    """Stop-word mid-conversation must flush the buffer: the next wake-word handover
    should send only what was said after the stop, not the whole session history."""
    service = make_service(wake_word="hey agent")

    def prime_buffer(buffer):
        # Simulate: the agent is already mid-conversation (a previous wake-word
        # handover already happened), an earlier turn was transcribed, and only
        # then does the user say the stop phrase (StopAgentToolExecutor calls
        # set_chat_mode(LISTEN) mid-session) — a real CONVERSATION->LISTEN transition.
        service.set_chat_mode(ChatMode.CONVERSATION)
        buffer.append("please remember my address is 42 main street")
        service.set_chat_mode(ChatMode.LISTEN)

    clients = await _run_execute_with_transcription(
        service, "ok agent, what time is it", prime_buffer=prime_buffer
    )

    assert service.current_chat_mode == ChatMode.CONVERSATION
    sent_text = clients.rt_agent_client.send_conversation_item_to_server.await_args.args[0]
    assert "42 main street" not in sent_text
    assert "what time is it" in sent_text


@pytest.mark.asyncio
async def test_transcript_without_wake_word_stays_in_listen(make_service):
    service = make_service(wake_word="hey agent")

    clients = await _run_execute_with_transcription(service, "what time is it")

    assert service.current_chat_mode == ChatMode.LISTEN
    clients.rt_agent_client.send_conversation_item_to_server.assert_not_awaited()
    clients.rt_agent_client.request_response.assert_not_awaited()
    # The user-visible bug is audio reaching the agent before the wake word:
    # in LISTEN the message must go to transcription only.
    clients.transcription_client.process_message.assert_awaited()
    clients.rt_agent_client.process_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_transcription_client_downgrades_listen_to_conversation(
    make_service, captured_log_messages
):
    service = make_service(wake_word="hey agent")
    assert service.current_chat_mode == ChatMode.LISTEN

    rt_agent_client = AsyncMock()
    rt_agent_client.handle_messages = _idle_loop
    rt_agent_client.process_message = AsyncMock(return_value=None)
    service.factory.create.return_value = rt_agent_client
    service.transcription_client_factory.create.return_value = None
    service.client_websocket.scope = {"subprotocols": []}
    service.client_websocket.receive_json = AsyncMock(side_effect=WebSocketDisconnect())

    await service.execute()

    assert service.current_chat_mode == ChatMode.CONVERSATION
    assert any("no transcription client" in message for message in captured_log_messages)


def test_maybe_create_transcription_delegates_to_factory(service, mock_tool_manager):
    mock_factory = MagicMock(spec=ITranscriptionClientFactory)
    service.transcription_client_factory = mock_factory
    mock_buffer = MagicMock(spec=ChatSummarizedBuffer)

    service._maybe_create_transcription_client(mock_buffer)

    mock_factory.create.assert_called_once()
    call_kwargs = mock_factory.create.call_args[1]
    assert call_kwargs["config"] is service.realtime_agent_chat_data
    assert call_kwargs["buffer"] is mock_buffer
