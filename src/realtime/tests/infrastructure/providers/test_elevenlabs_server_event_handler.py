"""ElevenLabsServerEventHandler translates ElevenLabs Conversational AI events into the
OpenAI-shaped events the frontend understands, runs tool calls and records events.

Everything enters through `handle_event`. The client is a stand-in recording what is
sent; the DB write is the recorded side effect, so it is mocked.
"""

import base64
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.tool_manager_service import ToolManagerService
from domain.models.realtime_tool import RealtimeTool, ToolParameters
from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import ElevenLabsRealtimeAgentClient
from infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler import (
    ElevenLabsServerEventHandler,
)
from tool_executors import BaseToolExecutor
from utils.singleton_meta import SingletonMeta

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def db_write():
    with patch(
        "infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db",
        new_callable=AsyncMock,
    ) as write:
        yield write


@pytest.fixture
def client():
    sent: list[dict] = []
    to_server: list[dict] = []

    async def send_client(payload):
        sent.append(payload)

    async def send_server(payload):
        to_server.append(payload)

    return SimpleNamespace(
        connection_key="conn_key",
        org_id=33,
        user_id=4,
        tool_prefix="o1r2__",
        is_twilio=False,
        _down_resample_state=None,
        sent=sent,
        to_server=to_server,
        send_client=send_client,
        send_server=send_server,
        call_tool=AsyncMock(),
    )


@pytest.fixture
def handler(client):
    return ElevenLabsServerEventHandler(client)


def _types(client) -> list[str]:
    return [event["type"] for event in client.sent]


def _audio(samples: int = 160) -> dict:
    pcm = struct.pack(f"<{samples}h", *([0] * samples))
    return {"type": "audio", "audio_event": {"audio_base_64": base64.b64encode(pcm).decode()}}


def _tool_call(tool_name: str, parameters=None, call_id="tc1") -> dict:
    return {
        "type": "client_tool_call",
        "client_tool_call": {"tool_call_id": call_id, "tool_name": tool_name, "parameters": parameters or {}},
    }


@pytest.mark.parametrize(
    ("is_twilio", "expected_bytes"),
    [
        # Browser plays PCM 24 kHz: 160 samples at 16 kHz become 240 16-bit samples.
        (False, 480),
        # Twilio plays µ-law 8 kHz: 320 samples at 16 kHz become about 160 one-byte samples.
        (True, 160),
    ],
    ids=["browser-pcm-24k", "twilio-ulaw-8k"],
)
async def test_agent_audio_is_converted_for_the_caller(handler, client, is_twilio, expected_bytes):
    client.is_twilio = is_twilio

    await handler.handle_event(_audio(320 if is_twilio else 160))

    (delta,) = [event for event in client.sent if event["type"] == "response.audio.delta"]
    assert len(base64.b64decode(delta["delta"])) == pytest.approx(expected_bytes, abs=2)


async def test_an_agent_turn_opens_a_response_and_its_transcript_closes_it(handler, client, captured_log_messages):
    reply = "Your account balance is 1234 dollars."

    await handler.handle_event(_audio())
    await handler.handle_event({"type": "agent_response", "agent_response_event": {"agent_response": reply}})

    assert _types(client) == [
        "conversation.item.created",
        "response.created",
        "response.output_item.added",
        "conversation.item.created",
        "response.audio.delta",
        "response.audio_transcript.delta",
        "response.audio_transcript.done",
        "response.audio.done",
        "response.output_item.done",
        "response.done",
    ]
    assert client.sent[6]["transcript"] == reply
    # The turn is traceable in the logs, but its text may hold user data.
    assert any(f"{len(reply)} characters" in message for message in captured_log_messages)
    assert not any("Your account" in message for message in captured_log_messages)


async def test_agent_transcript_without_an_open_response_is_dropped(handler, client):
    await handler.handle_event({"type": "agent_response", "agent_response_event": {"agent_response": "hi"}})

    assert client.sent == []


async def test_interruption_stops_playback_and_the_next_audio_starts_a_new_response(handler, client):
    await handler.handle_event(_audio())
    first = next(event["response"]["id"] for event in client.sent if event["type"] == "response.created")
    client.sent.clear()

    await handler.handle_event({"type": "interruption"})
    await handler.handle_event(_audio())

    assert client.sent[0]["type"] == "input_audio_buffer.speech_started"
    second = next(event["response"]["id"] for event in client.sent if event["type"] == "response.created")
    assert second != first


@pytest.mark.parametrize(
    ("event", "expected_types"),
    [
        (
            {"type": "conversation_initiation_metadata", "conversation_initiation_metadata_event": {"conversation_id": "c1"}},
            ["session.created"],
        ),
        (
            {"type": "user_transcript", "user_transcription_event": {"user_transcript": "hello world"}},
            ["conversation.item.created", "conversation.item.input_audio_transcription.completed"],
        ),
        ({"type": "user_transcript", "user_transcription_event": {"user_transcript": ""}}, []),
        ({"type": "audio", "audio_event": {"audio_base_64": ""}}, []),
        ({"type": "totally_unknown_event"}, []),
    ],
    ids=["session-start", "user-transcript", "empty-transcript", "empty-audio", "unknown"],
)
async def test_event_reaches_the_frontend_and_is_recorded(handler, client, db_write, event, expected_types):
    await handler.handle_event(event)

    assert _types(client) == expected_types
    kwargs = db_write.await_args.kwargs
    assert (kwargs["data"], kwargs["connection_key"], kwargs["org_id"], kwargs["user_id"]) == (event, "conn_key", 33, 4)


async def test_ping_is_answered_with_a_pong(handler, client):
    await handler.handle_event({"type": "ping", "ping_event": {"event_id": 7}})

    assert client.to_server == [{"type": "pong", "event_id": 7}]
    assert client.sent == []


@pytest.mark.parametrize(
    ("reported_name", "local_name"),
    [
        ("knowledge_tool", "knowledge_tool"),
        # The remote tool record carries this configuration's prefix; it is stripped.
        ("o1r2__" + "YesNoTool" * 6, "YesNoTool" * 6),
        # Another configuration's prefix is not ours to strip.
        ("o1r3__lookup", "o1r3__lookup"),
    ],
    ids=["plain", "own-prefix-long-name", "other-configs-prefix"],
)
async def test_tool_call_is_shown_and_run_under_its_local_name(handler, client, reported_name, local_name):
    await handler.handle_event(_tool_call(reported_name, {"query": "test"}))

    client.call_tool.assert_awaited_once_with("tc1", local_name, {"query": "test"})
    done = next(event for event in client.sent if event["type"] == "response.function_call_arguments.done")
    assert (done["call_id"], done["name"], done["arguments"]) == ("tc1", local_name, '{"query": "test"}')


class RecordingToolExecutor(BaseToolExecutor):
    def __init__(self, tool_name: str):
        super().__init__(tool_name=tool_name)
        self.calls: list[dict] = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "done"

    async def get_realtime_tool_model(self):
        return RealtimeTool(name=self.tool_name, parameters=ToolParameters(properties={}))


@pytest.fixture
def tool_manager_service():
    # A process-wide singleton; drop it so each test registers its own executors.
    SingletonMeta._instances.pop(ToolManagerService, None)
    yield ToolManagerService(python_code_executor_service=MagicMock(), knowledge_client=MagicMock())
    SingletonMeta._instances.pop(ToolManagerService, None)


@pytest.mark.parametrize("reported_name", ["lookup", "o1r10__lookup"], ids=["local-name", "remote-record-name"])
async def test_tool_call_reaches_the_local_executor_through_the_real_client(tool_manager_service, reported_name):
    executor = RecordingToolExecutor("lookup")
    tool_manager_service.connection_tool_executors["conn_1"] = [executor]
    client = ElevenLabsRealtimeAgentClient(
        api_key="key", connection_key="conn_1", tool_manager_service=tool_manager_service, org_id=1,
        rt_agent_definition_id=10,
    )
    client.send_server = AsyncMock()
    client.send_client = AsyncMock()

    await client.server_event_handler.handle_event(_tool_call(reported_name, {"order_id": "42"}))

    assert executor.calls == [{"order_id": "42"}]
