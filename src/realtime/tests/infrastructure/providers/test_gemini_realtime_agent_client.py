"""GeminiRealtimeAgentClient: the adapter to the Gemini Live API.

The Gemini SDK is the external boundary. FakeGeminiLive stands in for
`genai.Client().aio.live.connect()`: every connect opens a FakeSession that records
its config and everything sent to it, and replays the server messages scripted for it.
"""

import asyncio
import audioop
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from domain.models.realtime_tool import RealtimeTool
from infrastructure.providers.gemini.gemini_realtime_agent_client import GeminiRealtimeAgentClient
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL

pytestmark = pytest.mark.asyncio


class FakeSession:
    def __init__(self, config, messages):
        self.config = config
        self.messages = messages  # a list of server messages, or an exception to raise
        self.audio: list[types.Blob] = []
        self.turns: list[tuple[types.Content, bool]] = []
        self.tool_responses: list[types.FunctionResponse] = []
        self.fail_tool_response = False
        self.closed = False

    async def receive(self):
        if isinstance(self.messages, BaseException):
            raise self.messages
        for message in self.messages:
            yield message
        if self.messages is HANG:
            await asyncio.Event().wait()

    async def send_realtime_input(self, audio):
        self.audio.append(audio)

    async def send_client_content(self, turns, turn_complete):
        self.turns.append((turns, turn_complete))

    async def send_tool_response(self, function_responses):
        if self.fail_tool_response:
            raise RuntimeError("ws closed")
        self.tool_responses.extend(function_responses)


HANG: list = []


class FakeGeminiLive:
    """`aio.live.connect(model, config)`: session N replays `scripts[N]` (default: hang)."""

    def __init__(self):
        self.scripts: list = []
        self.sessions: list[FakeSession] = []
        self.refuse_after: int | None = None

    def connect(self, model, config):
        live = self

        class _SessionContext:
            async def __aenter__(self):
                if live.refuse_after is not None and len(live.sessions) >= live.refuse_after:
                    raise ConnectionError("Gemini refused the connection")
                index = len(live.sessions)
                session = FakeSession(config, live.scripts[index] if index < len(live.scripts) else HANG)
                live.sessions.append(session)
                return session

            async def __aexit__(self, *exc_info):
                live.sessions[-1].closed = True

        return _SessionContext()


@pytest.fixture
def live():
    fake = FakeGeminiLive()
    with patch("infrastructure.providers.gemini.gemini_realtime_agent_client.genai") as genai:
        genai.Client.return_value = MagicMock()
        genai.Client.return_value.aio.live.connect = fake.connect
        yield fake


def _tool(name="echo", description="echo tool") -> RealtimeTool:
    tool = RealtimeTool(
        name=name,
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    )
    # description is a property backed by _description, not a Pydantic field.
    tool.description = description
    return tool


def _client(live, **overrides) -> GeminiRealtimeAgentClient:
    return GeminiRealtimeAgentClient(
        **{
            "api_key": "test_key",
            "connection_key": "conn_1",
            "on_server_event": AsyncMock(),
            "tool_manager_service": AsyncMock(),
            "instructions": "You are helpful.",
            **overrides,
        }
    )


def _system_instruction(session: FakeSession) -> str:
    return session.config.system_instruction.parts[0].text


async def _reconnect(client) -> FakeSession:
    await client.close()
    await client.connect()


@pytest.mark.parametrize(("voice", "expected_voice"), [("Kore", "Kore"), ("bogus", "Puck")])
async def test_connect_configures_voice_instructions_and_tools(live, voice, expected_voice):
    client = _client(live, voice=voice, rt_tools=[_tool("search", "search the web"), _tool("b")])

    await client.connect()

    config = live.sessions[0].config
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == expected_voice
    assert _system_instruction(live.sessions[0]) == "You are helpful."
    ((declarations,),) = [tool.values() for tool in config.tools]
    assert [(declaration["name"], declaration["description"]) for declaration in declarations] == [
        ("search", "search the web"),
        ("b", "echo tool"),
    ]
    assert declarations[0]["parameters"] == {
        "type": "OBJECT", "properties": {"text": {"type": "string"}}, "required": ["text"],
    }


async def test_constructing_the_client_does_not_connect(live):
    _client(live)

    assert live.sessions == []


async def test_a_reconnected_session_continues_the_conversation(live):
    client = _client(live)
    client.tool_manager_service.execute = AsyncMock(return_value="sunny")
    await client.connect()
    await client.send_conversation_item_to_server("what's the weather")
    await client.call_tool("c1", "weather", {"city": "Kyiv"})

    await _reconnect(client)

    instruction = _system_instruction(live.sessions[1])
    assert instruction.startswith("You are helpful.\n\n---\nConversation so far")
    assert "User: what's the weather" in instruction
    assert "Assistant: [Tool weather({'city': 'Kyiv'}) → sunny]" in instruction


async def test_twilio_audio_is_sent_as_16k_pcm(live):
    client = _client(live)
    await client.connect()

    await client.send_audio(base64.b64encode(audioop.lin2ulaw(b"\x00\x00" * 160, 2)).decode())

    (blob,) = live.sessions[0].audio
    assert blob.mime_type == "audio/pcm;rate=16000"
    # 160 samples at 8 kHz are about 320 16-bit samples at 16 kHz (the resampler lags by one).
    assert len(blob.data) // 2 == pytest.approx(320, abs=2)


async def test_nothing_is_sent_while_no_session_is_open(live):
    client = _client(live)
    client.tool_manager_service.execute = AsyncMock(return_value="ok")

    await client.send_audio(base64.b64encode(b"\xff" * 10).decode())
    await client.send_conversation_item_to_server("hello")
    await client.call_tool("c1", "echo", {})
    await client.replay_audio_buffer()

    assert live.sessions == []


async def test_typed_text_is_sent_as_a_complete_user_turn(live):
    client = _client(live)
    await client.connect()

    await client.send_conversation_item_to_server("hello")

    ((content, turn_complete),) = live.sessions[0].turns
    assert (content.role, content.parts[0].text, turn_complete) == ("user", "hello", True)


async def test_tool_result_is_sent_back_for_its_call(live):
    client = _client(live)
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    await client.connect()

    await client.call_tool("c1", "echo", {"text": "hi"})

    client.tool_manager_service.execute.assert_awaited_once_with(
        connection_key="conn_1", tool_name="echo", call_arguments={"text": "hi"}
    )
    (response,) = live.sessions[0].tool_responses
    assert (response.id, response.name, response.response) == ("c1", "echo", {"result": "ok"})


async def test_tool_result_is_dropped_when_the_session_was_replaced_meanwhile(live):
    """Gemini would reject a response for a call it never made in the new session."""
    client = _client(live)
    live.scripts = [[]]  # the first session closes at once; the reconnected one stays open
    reconnected = asyncio.Event()

    async def slow_tool(**kwargs):
        await reconnected.wait()
        return "result"

    client.tool_manager_service.execute = slow_tool
    await client.connect()
    tool_call = asyncio.create_task(client.call_tool("c1", "echo", {}))
    loop = asyncio.create_task(client.handle_messages())
    while len(live.sessions) < 2:
        await asyncio.sleep(0)
    reconnected.set()
    await tool_call
    loop.cancel()
    await loop

    assert all(session.tool_responses == [] for session in live.sessions)


async def test_a_failed_tool_response_send_is_not_raised(live):
    client = _client(live)
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    await client.connect()
    live.sessions[0].fail_tool_response = True

    await client.call_tool("c1", "echo", {})


async def test_tool_failure_reaches_gemini_and_the_history_without_the_exception_text(live, captured_log_messages):
    client = _client(live)
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))
    await client.connect()

    await client.call_tool("c1", "echo", {"text": "hi"})

    (response,) = live.sessions[0].tool_responses
    result = response.response["result"]
    assert result.startswith("Tool execution failed") and SECRET_SENTINEL not in result
    correlation_id = PUBLIC_ERROR_REFERENCE.search(result).group(1)
    (log,) = [message for message in captured_log_messages if correlation_id in message]
    assert SECRET_SENTINEL in log
    # History is replayed into the system instruction after a reconnect.
    await _reconnect(client)
    assert SECRET_SENTINEL not in _system_instruction(live.sessions[1])


async def test_close_is_idempotent_and_safe_to_race(live):
    client = _client(live)
    await client.close()
    await client.connect()

    results = await asyncio.gather(client.close(), client.close(), return_exceptions=True)

    assert results == [None, None]
    assert live.sessions[0].closed


async def test_server_messages_reach_the_frontend_and_a_closed_session_is_reopened(live):
    client = _client(live)
    live.scripts = [[types.LiveServerMessage(setup_complete=types.LiveServerSetupComplete())], []]
    live.refuse_after = 2
    await client.connect()

    await client.handle_messages()

    sent_types = [call.args[0]["type"] for call in client.on_server_event.await_args_list]
    assert sent_types == ["session.created"]
    # Session 1 ended normally → reopened; session 2 ended → the third connect was refused.
    assert len(live.sessions) == 2
    assert all(session.closed for session in live.sessions)


async def test_a_receive_error_ends_the_loop_without_reconnecting(live):
    client = _client(live)
    live.scripts = [RuntimeError("network error")]
    await client.connect()

    await client.handle_messages()

    assert len(live.sessions) == 1
    assert live.sessions[0].closed


async def test_cancelling_the_loop_does_not_reconnect(live):
    client = _client(live)
    await client.connect()

    task = asyncio.create_task(client.handle_messages())
    await asyncio.sleep(0)
    task.cancel()
    await task

    assert len(live.sessions) == 1


async def test_buffered_caller_audio_is_replayed_once_into_a_new_session(live):
    client = _client(live)
    await client.connect()
    for chunk in (b"\x01\x00" * 48, b"\x02\x00" * 48):
        await client.process_message({"type": "input_audio_buffer.append", "audio": base64.b64encode(chunk).decode()})
    await _reconnect(client)

    await client.replay_audio_buffer()
    await client.replay_audio_buffer()

    # 48 samples at 24 kHz become 32 at 16 kHz.
    assert [blob.data for blob in live.sessions[1].audio] == [b"\x01\x00" * 32, b"\x02\x00" * 32]
