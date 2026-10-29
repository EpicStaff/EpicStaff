import asyncio
import base64
from typing import NamedTuple

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import WebSocket, WebSocketDisconnect
from src.shared.models import RealtimeAgentChatData
from domain.models.chat_mode import ChatMode
from domain.ports.i_summarization_client import ISummarizationClient
from domain.ports.i_transcription_client_factory import ITranscriptionClientFactory
from application.conversation_service import ConversationService
from application.tool_manager_service import ToolManagerService
from infrastructure.providers.factory import RealtimeAgentClientFactory
from infrastructure.providers.gemini.gemini_realtime_agent_client import GeminiRealtimeAgentClient
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL
from tests.infrastructure.providers.gemini_live_fakes import (
    SESSION_RECORD_PATCH,
    patch_gemini_clock,
    patched_gemini_live,
    resumption_update,
    server_close,
)


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


# ---------------------------------------------------------------------------
# Constructor registers tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rt_provider", ["openai", "elevenlabs"])
def test_stop_agent_tool_gets_a_mode_controller_except_on_elevenlabs(make_service, mock_tool_manager, rt_provider):
    """ElevenLabs has built-in VAD, so the StopAgent tool is disabled there (no controller)."""
    service = make_service(rt_provider=rt_provider)

    _, kwargs = mock_tool_manager.register_tools_from_rt_agent_chat_data.call_args
    assert kwargs["chat_mode_controller"] is (None if rt_provider == "elevenlabs" else service)


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
@pytest.mark.parametrize(
    "session_ending",
    [server_close(1000, "go away elapsed"), RuntimeError("protocol error")],
    ids=["server-close-reopened-by-the-message-loop", "receive-error-reopened-by-execute"],
)
async def test_a_lost_gemini_session_is_resumed_exactly_once_with_only_the_audio_it_missed(
    make_service, monkeypatch, session_ending
):
    """A server close is reopened inside the Gemini message loop, which keeps running;
    any other end of the loop is reopened by execute(). Never both."""
    service = make_service(wake_word=None, rt_provider="gemini")
    clock = patch_gemini_clock(monkeypatch)
    heard_before_the_handle, said_during_the_outage = b"\x01\x00" * 48, b"\x02\x00" * 48
    with patched_gemini_live() as live, patch(SESSION_RECORD_PATCH, new_callable=AsyncMock):
        live.scripts = [[resumption_update("h1", True), session_ending]]
        service.factory.create.return_value = GeminiRealtimeAgentClient(
            api_key="api_key",
            connection_key="test_key",
            on_server_event=service.client_websocket.send_json,
            tool_manager_service=AsyncMock(),
            instructions="Be helpful.",
        )
        service.transcription_client_factory.create.return_value = None
        service.client_websocket.scope = {"subprotocols": []}

        async def caller_messages():
            yield {"type": "input_audio_buffer.append", "audio": base64.b64encode(heard_before_the_handle).decode()}
            clock.now += 1  # the handle is stored after this audio
            async with asyncio.timeout(2):
                while not live.sessions[0].closed:
                    await asyncio.sleep(0)
            clock.now += 1
            yield {"type": "input_audio_buffer.append", "audio": base64.b64encode(said_during_the_outage).decode()}
            async with asyncio.timeout(2):
                while len(live.sessions) < 2:
                    await asyncio.sleep(0)
            yield {"type": "session.update"}
            raise WebSocketDisconnect()

        messages = caller_messages()

        async def receive_json():
            return await anext(messages)

        service.client_websocket.receive_json = receive_json

        await service.execute()

    _, resumed = live.sessions
    assert resumed.config.session_resumption.handle == "h1"
    assert resumed.config.system_instruction.parts[0].text == "Be helpful."
    assert resumed.turns == []
    # 48 samples at 24 kHz become 32 at 16 kHz. The resumed session gets the outage
    # audio once (replayed, or live when the loop had already reopened it), never
    # the audio Gemini heard before the handle.
    assert [blob.data for blob in resumed.audio] == [b"\x02\x00" * 32]
    assert resumed.closed


@pytest.mark.asyncio
async def test_missing_transcription_client_downgrades_listen_to_conversation(make_service):
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
