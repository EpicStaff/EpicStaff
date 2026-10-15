"""
Tests for ElevenLabsServerEventHandler event routing and state management.
`save_realtime_session_item_to_db` is patched out to avoid DB dependency.
"""
import base64
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from application.tool_manager_service import ToolManagerService
from domain.models.realtime_tool import RealtimeTool, ToolParameters
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import remote_tool_name
from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler import (
    ElevenLabsServerEventHandler,
)
from tool_executors import BaseToolExecutor
from utils.singleton_meta import SingletonMeta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    c = MagicMock()
    c.connection_key = "conn_key"
    c.tool_prefix = "o1r2__"
    c.is_twilio = False
    c._down_resample_state = None
    c.send_client = AsyncMock()
    c.send_server = AsyncMock()
    c.call_tool = AsyncMock()
    return c


@pytest.fixture
def handler(client):
    return ElevenLabsServerEventHandler(client)


def _silence_pcm16_b64(n: int = 160) -> str:
    return base64.b64encode(struct.pack(f"<{n}h", *([0] * n))).decode()


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_routes_audio(mock_db, handler, client):
    data = {"type": "audio", "audio_event": {"audio_base_64": _silence_pcm16_b64()}}
    await handler.handle_event(data)
    client.send_client.assert_awaited()


@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_routes_interruption(mock_db, handler, client):
    await handler.handle_event({"type": "interruption"})
    # interruption emits input_audio_buffer.speech_started to client
    sent_types = [call.args[0]["type"] for call in client.send_client.call_args_list]
    assert "input_audio_buffer.speech_started" in sent_types


@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_routes_user_transcript(mock_db, handler, client):
    data = {
        "type": "user_transcript",
        "user_transcription_event": {"user_transcript": "hello"},
    }
    await handler.handle_event(data)
    client.send_client.assert_awaited()


@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_forwards_org_id_to_db_write(mock_db, handler, client):
    client.org_id = 33
    await handler.handle_event({"type": "ping"})
    _, kwargs = mock_db.call_args
    assert kwargs.get("org_id") == 33


@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_ignored_for_unknown_type(mock_db, handler, client):
    await handler.handle_event({"type": "totally_unknown_event"})
    client.send_client.assert_not_awaited()


@pytest.mark.asyncio
@patch("infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db", new_callable=AsyncMock)
async def test_handle_event_saves_to_db(mock_db, handler):
    await handler.handle_event({"type": "interruption"})
    mock_db.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_interruption
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interruption_resets_response_id(handler, client):
    handler._current_response_id = "resp_abc"
    handler._current_item_id = "item_abc"
    await handler._handle_interruption({})
    assert handler._current_response_id is None
    assert handler._current_item_id is None


@pytest.mark.asyncio
async def test_interruption_emits_speech_started(handler, client):
    await handler._handle_interruption({})
    client.send_client.assert_awaited_once()
    sent = client.send_client.call_args[0][0]
    assert sent["type"] == "input_audio_buffer.speech_started"


# ---------------------------------------------------------------------------
# _handle_audio — is_twilio routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audio_twilio_calls_pcm16k_to_ulaw8k(handler, client):
    """When is_twilio=True the output audio must be µ-law 8kHz (1 byte/sample)."""
    client.is_twilio = True
    # Force a response/item to exist so _handle_audio doesn't short-circuit
    handler._current_response_id = "resp_1"
    handler._current_item_id = "item_1"
    handler._assistant_output_index = 0

    audio_b64 = _silence_pcm16_b64(320)  # 320 samples of silence
    await handler._handle_audio({"audio_event": {"audio_base_64": audio_b64}})

    client.send_client.assert_awaited()
    delta_calls = [c for c in client.send_client.call_args_list
                   if c[0][0].get("type") == "response.audio.delta"]
    assert len(delta_calls) == 1

    # The delta should be µ-law: 1 byte per sample ≈ 160 bytes for 320 pcm16k samples
    delta_b64 = delta_calls[0][0][0]["delta"]
    ulaw_bytes = base64.b64decode(delta_b64)
    assert len(ulaw_bytes) > 0
    # µ-law 8kHz output is half the PCM 16kHz input (downsampled)
    assert len(ulaw_bytes) <= 320


@pytest.mark.asyncio
async def test_audio_browser_calls_pcm16k_to_pcm24k(handler, client):
    """When is_twilio=False the output audio must be PCM 24kHz."""
    client.is_twilio = False
    handler._current_response_id = "resp_1"
    handler._current_item_id = "item_1"
    handler._assistant_output_index = 0

    n_in = 160
    audio_b64 = _silence_pcm16_b64(n_in)
    await handler._handle_audio({"audio_event": {"audio_base_64": audio_b64}})

    delta_calls = [c for c in client.send_client.call_args_list
                   if c[0][0].get("type") == "response.audio.delta"]
    assert len(delta_calls) == 1

    delta_b64 = delta_calls[0][0][0]["delta"]
    pcm_bytes = base64.b64decode(delta_b64)
    n_out = len(pcm_bytes) // 2  # int16
    # 24kHz output should be ~1.5x the 16kHz input
    assert n_out > n_in


@pytest.mark.asyncio
async def test_audio_empty_payload_does_nothing(handler, client):
    """Empty audio_base_64 should not call send_client."""
    await handler._handle_audio({"audio_event": {"audio_base_64": ""}})
    client.send_client.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_client_tool_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_call_invokes_client_call_tool(handler, client):
    handler._current_response_id = "resp_1"
    data = {
        "type": "client_tool_call",
        "client_tool_call": {
            "tool_call_id": "tc1",
            "tool_name": "knowledge_tool",
            "parameters": {"query": "test"},
        },
    }
    await handler._handle_client_tool_call(data)
    client.call_tool.assert_awaited_once_with("tc1", "knowledge_tool", {"query": "test"})


@pytest.mark.asyncio
async def test_tool_call_emits_function_call_created(handler, client):
    handler._current_response_id = "resp_1"
    data = {
        "type": "client_tool_call",
        "client_tool_call": {"tool_call_id": "tc2", "tool_name": "t", "parameters": {}},
    }
    await handler._handle_client_tool_call(data)
    sent_types = [c[0][0]["type"] for c in client.send_client.call_args_list]
    assert "conversation.item.created" in sent_types
    assert "response.function_call_arguments.done" in sent_types


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
    yield ToolManagerService(
        python_code_executor_service=MagicMock(), knowledge_client=MagicMock()
    )
    SingletonMeta._instances.pop(ToolManagerService, None)


@pytest.fixture
def real_client(tool_manager_service):
    elevenlabs_client = ElevenLabsRealtimeAgentClient(
        api_key="key",
        connection_key="conn_1",
        tool_manager_service=tool_manager_service,
        org_id=1,
        rt_agent_definition_id=10,
    )
    elevenlabs_client.send_server = AsyncMock()
    elevenlabs_client.send_client = AsyncMock()
    return elevenlabs_client


@pytest.mark.asyncio
@pytest.mark.parametrize("prefixed", [False, True], ids=["local_name", "remote_record_name"])
async def test_tool_call_reaches_the_local_executor_under_either_tool_name(
    real_client, tool_manager_service, prefixed
):
    executor = RecordingToolExecutor("lookup")
    tool_manager_service.connection_tool_executors["conn_1"] = [executor]
    local_tool = RealtimeTool(name="lookup", parameters=ToolParameters(properties={}))
    remote_name = remote_tool_name(real_client.tool_prefix, local_tool)
    assert remote_name == "o1r10__lookup"
    reported_name = remote_name if prefixed else "lookup"
    data = {
        "type": "client_tool_call",
        "client_tool_call": {
            "tool_call_id": "tc1",
            "tool_name": reported_name,
            "parameters": {"order_id": "42"},
        },
    }

    await real_client.server_event_handler._handle_client_tool_call(data)

    assert executor.calls == [{"order_id": "42"}]
    browser_names = {
        event.args[0]["item"]["name"]
        for event in real_client.send_client.await_args_list
        if event.args[0].get("type") == "conversation.item.created"
        and event.args[0]["item"].get("type") == "function_call"
    }
    assert browser_names == {"lookup"}


@pytest.mark.asyncio
async def test_tool_call_prefixed_for_another_configuration_is_not_stripped(handler, client):
    data = {
        "type": "client_tool_call",
        "client_tool_call": {
            "tool_call_id": "tc1",
            "tool_name": "o1r3__lookup",
            "parameters": {},
        },
    }

    await handler._handle_client_tool_call(data)

    client.call_tool.assert_awaited_once_with("tc1", "o1r3__lookup", {})


@pytest.mark.asyncio
async def test_tool_call_with_the_short_prefix_and_a_long_tool_name_routes_to_the_local_name(
    handler, client
):
    long_tool_name = "YesNoTool" * 6
    data = {
        "type": "client_tool_call",
        "client_tool_call": {
            "tool_call_id": "tc1",
            "tool_name": f"o1r2__{long_tool_name}",
            "parameters": {"answer": "yes"},
        },
    }

    await handler._handle_client_tool_call(data)

    client.call_tool.assert_awaited_once_with("tc1", long_tool_name, {"answer": "yes"})


# ---------------------------------------------------------------------------
# _handle_agent_response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_response_logs_transcript_length_but_not_its_text(
    handler, client, captured_log_messages
):
    handler._current_response_id = "resp_1"
    handler._current_item_id = "item_1"
    reply = "Your account balance is 1234 dollars."
    data = {"type": "agent_response", "agent_response_event": {"agent_response": reply}}

    await handler._handle_agent_response(data)

    sent_types = [c[0][0]["type"] for c in client.send_client.call_args_list]
    assert "response.done" in sent_types
    assert any(f"{len(reply)} characters" in message for message in captured_log_messages)
    assert not any("Your account" in message for message in captured_log_messages)


# ---------------------------------------------------------------------------
# _handle_user_transcript
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_transcript_emits_transcription_completed(handler, client):
    data = {
        "type": "user_transcript",
        "user_transcription_event": {"user_transcript": "hello world"},
    }
    await handler._handle_user_transcript(data)
    sent_types = [c[0][0]["type"] for c in client.send_client.call_args_list]
    assert "conversation.item.input_audio_transcription.completed" in sent_types


@pytest.mark.asyncio
async def test_user_transcript_empty_does_nothing(handler, client):
    data = {"type": "user_transcript", "user_transcription_event": {"user_transcript": ""}}
    await handler._handle_user_transcript(data)
    client.send_client.assert_not_awaited()
