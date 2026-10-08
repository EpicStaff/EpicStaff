"""
Tests for GeminiRealtimeAgentClient.

The Google Generative AI SDK (genai) is patched at module level via the
`mock_genai` autouse fixture — no real API calls are made.
Each test gets a pre-built client with a ready AsyncMock _session.
"""
import asyncio
import base64
import audioop
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from infrastructure.providers.gemini.gemini_realtime_agent_client import (
    GeminiRealtimeAgentClient,
)
from domain.models.realtime_tool import RealtimeTool
from tests.conftest import PUBLIC_ERROR_REFERENCE, SECRET_SENTINEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rt_tool(name="echo", description="echo tool") -> RealtimeTool:
    # description is a property backed by _description (not a Pydantic field),
    # so it must be set explicitly after construction.
    tool = RealtimeTool(
        name=name,
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    tool.description = description
    return tool


def _make_server_msg(**overrides):
    """Minimal Gemini LiveServerMessage-like mock."""
    r = MagicMock()
    r.setup_complete = None
    r.server_content = None
    r.tool_call = None
    r.go_away = None
    r.session_resumption_update = None
    for k, v in overrides.items():
        setattr(r, k, v)
    return r


async def _empty_receive():
    """Async generator that ends immediately (simulates server-close)."""
    return
    yield  # pragma: no cover — makes this an async generator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_genai():
    """Prevent all real genai.Client construction."""
    with patch(
        "infrastructure.providers.gemini.gemini_realtime_agent_client.genai"
    ) as mg:
        mg.Client.return_value = MagicMock()
        yield mg


@pytest.fixture
def client():
    """GeminiRealtimeAgentClient with a ready mock session."""
    c = GeminiRealtimeAgentClient(
        api_key="test_key",
        connection_key="conn_1",
        on_server_event=AsyncMock(),
        tool_manager_service=AsyncMock(),
    )
    mock_session = AsyncMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)
    c._session = mock_session
    c._session_cm = mock_session_cm
    return c


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_invalid_voice_falls_back_to_puck():
    c = GeminiRealtimeAgentClient(api_key="k", connection_key="c", voice="bogus")
    assert c.voice == "Puck"


def test_valid_voice_kept():
    for voice in ("Puck", "Charon", "Kore", "Fenrir", "Aoede"):
        c = GeminiRealtimeAgentClient(api_key="k", connection_key="c", voice=voice)
        assert c.voice == voice


def test_session_version_starts_at_zero(client):
    assert client._session_version == 0


def test_session_is_none_before_connect():
    c = GeminiRealtimeAgentClient(api_key="k", connection_key="c")
    # __init__ should NOT open any connection
    assert c._session is None
    assert c._session_cm is None


# ---------------------------------------------------------------------------
# _build_tools
# ---------------------------------------------------------------------------

def test_build_tools_empty_returns_empty(client):
    assert client._build_tools([]) == []


def test_build_tools_single_tool(client):
    tool = _make_rt_tool("search", "search the web")
    result = client._build_tools([tool])
    assert len(result) == 1
    decl = result[0]["function_declarations"][0]
    assert decl["name"] == "search"
    assert decl["description"] == "search the web"
    assert "text" in decl["parameters"]["properties"]


def test_build_tools_multiple_tools(client):
    tools = [_make_rt_tool("a"), _make_rt_tool("b"), _make_rt_tool("c")]
    result = client._build_tools(tools)
    names = [d["name"] for d in result[0]["function_declarations"]]
    assert names == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _build_system_instruction
# ---------------------------------------------------------------------------

def test_system_instruction_no_history(client):
    client.instructions = "You are helpful."
    client._conversation_history = []
    assert client._build_system_instruction() == "You are helpful."


def test_system_instruction_injects_user_turns(client):
    client.instructions = "Base."
    client._conversation_history = [{"role": "user", "text": "Hello"}]
    result = client._build_system_instruction()
    assert "User: Hello" in result


def test_system_instruction_injects_model_turns(client):
    client.instructions = "Base."
    client._conversation_history = [{"role": "model", "text": "Hi!"}]
    result = client._build_system_instruction()
    assert "Assistant: Hi!" in result


def test_system_instruction_preserves_base(client):
    client.instructions = "My instructions."
    client._conversation_history = [{"role": "user", "text": "x"}]
    assert client._build_system_instruction().startswith("My instructions.")


# ---------------------------------------------------------------------------
# send_audio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_audio_drops_when_session_none(client):
    client._session = None
    b64 = base64.b64encode(b"\xff" * 100).decode()
    await client.send_audio(b64)  # must not raise
    # No session — nothing to assert on


@pytest.mark.asyncio
async def test_send_audio_calls_send_realtime_input(client):
    ulaw = audioop.lin2ulaw(b"\x00\x00" * 80, 2)
    b64 = base64.b64encode(ulaw).decode()
    await client.send_audio(b64)
    client._session.send_realtime_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_audio_resamples_8k_to_16k(client):
    """Output blob must use the 16kHz PCM mime type."""
    from google.genai import types as genai_types

    ulaw = audioop.lin2ulaw(b"\x00\x00" * 160, 2)  # 160 samples @ 8k
    b64 = base64.b64encode(ulaw).decode()
    await client.send_audio(b64)

    call_kwargs = client._session.send_realtime_input.call_args
    blob = call_kwargs.kwargs.get("audio") or call_kwargs.args[0]
    assert "rate=16000" in blob.mime_type


# ---------------------------------------------------------------------------
# send_conversation_item_to_server
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_conversation_item_drops_when_session_none(client):
    client._session = None
    await client.send_conversation_item_to_server("hello")  # must not raise


@pytest.mark.asyncio
async def test_send_conversation_item_calls_send_client_content(client):
    await client.send_conversation_item_to_server("hello")
    client._session.send_client_content.assert_awaited_once()


# ---------------------------------------------------------------------------
# call_tool — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_sends_tool_response(client):
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    await client.call_tool("c1", "echo", {"text": "hi"})
    client._session.send_tool_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_tool_saves_result_to_history(client):
    client.tool_manager_service.execute = AsyncMock(return_value="result_value")
    await client.call_tool("c1", "echo", {"text": "hi"})
    text = " ".join(e.get("text", "") for e in client._conversation_history)
    assert "echo" in text
    assert "result_value" in text


# ---------------------------------------------------------------------------
# call_tool — guard conditions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_drops_when_session_none(client):
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    client._session = None
    await client.call_tool("c1", "echo", {"text": "hi"})  # must not raise
    # No session — send_tool_response cannot be called


@pytest.mark.asyncio
async def test_call_tool_drops_when_session_version_changed(client):
    """Session replaced during execution → response must be discarded."""
    async def execute_and_replace(*a, **kw):
        client._session_version += 1  # simulate reconnect
        return "result"

    client.tool_manager_service.execute = execute_and_replace
    await client.call_tool("c1", "echo", {"text": "hi"})
    client._session.send_tool_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_tool_handles_send_failure_gracefully(client):
    """send_tool_response failure must not propagate to caller."""
    client.tool_manager_service.execute = AsyncMock(return_value="ok")
    client._session.send_tool_response.side_effect = RuntimeError("ws closed")
    await client.call_tool("c1", "echo", {"text": "hi"})  # must not raise


@pytest.mark.asyncio
async def test_call_tool_handles_execute_failure_gracefully(client):
    """Tool execution failure → error string sent, no exception raised."""
    client.tool_manager_service.execute = AsyncMock(
        side_effect=ValueError("tool broken")
    )
    await client.call_tool("c1", "echo", {"text": "hi"})  # must not raise
    client._session.send_tool_response.assert_awaited_once()


def _sent_tool_result(client) -> str:
    function_responses = client._session.send_tool_response.await_args.kwargs[
        "function_responses"
    ]
    assert len(function_responses) == 1
    return function_responses[0].response["result"]


@pytest.mark.asyncio
async def test_call_tool_failure_sends_fixed_result_without_exception_text(client):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("c1", "echo", {"text": "hi"})

    result = _sent_tool_result(client)
    assert SECRET_SENTINEL not in result
    assert result.startswith("Tool execution failed")
    assert PUBLIC_ERROR_REFERENCE.search(result)
    assert SECRET_SENTINEL not in str(client._session.send_tool_response.await_args)


@pytest.mark.asyncio
async def test_call_tool_failure_keeps_exception_text_out_of_replayed_history(client):
    """History is replayed into the system instruction after a reconnect."""
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("c1", "echo", {"text": "hi"})

    assert SECRET_SENTINEL not in client._build_system_instruction()


@pytest.mark.asyncio
async def test_call_tool_failure_logs_detail_under_the_sent_correlation_id(
    client, captured_log_messages
):
    client.tool_manager_service.execute = AsyncMock(side_effect=RuntimeError(SECRET_SENTINEL))

    await client.call_tool("c1", "echo", {"text": "hi"})

    correlation_id = PUBLIC_ERROR_REFERENCE.search(_sent_tool_result(client)).group(1)
    matching_logs = [message for message in captured_log_messages if correlation_id in message]
    assert len(matching_logs) == 1
    assert SECRET_SENTINEL in matching_logs[0]


# ---------------------------------------------------------------------------
# close — idempotency and locking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_clears_session_and_cm(client):
    await client.close()
    assert client._session is None
    assert client._session_cm is None


@pytest.mark.asyncio
async def test_close_is_idempotent(client):
    await client.close()
    await client.close()  # second call: _session_cm is None → no-op


@pytest.mark.asyncio
async def test_concurrent_close_calls_do_not_raise(client):
    results = await asyncio.gather(
        client.close(),
        client.close(),
        return_exceptions=True,
    )
    assert all(r is None for r in results)


@pytest.mark.asyncio
async def test_close_with_no_session_cm_is_noop(client):
    client._session_cm = None
    client._session = None
    await client.close()  # must not raise


# ---------------------------------------------------------------------------
# handle_messages — reconnect loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_messages_reconnects_after_server_close(client):
    """receive() ending normally → close() + connect() must be called."""
    client._session.receive = _empty_receive

    connect_calls = 0

    async def mock_connect():
        nonlocal connect_calls
        connect_calls += 1
        raise asyncio.CancelledError()  # abort loop after first reconnect

    with patch.object(client, "close", new_callable=AsyncMock) as mock_close, \
         patch.object(client, "connect", side_effect=mock_connect):
        await client.handle_messages()

    assert connect_calls == 1
    assert mock_close.await_count >= 1


@pytest.mark.asyncio
async def test_handle_messages_increments_session_version_on_reconnect(client):
    assert client._session_version == 0

    client._session.receive = _empty_receive
    reconnects = 0

    async def mock_connect():
        nonlocal reconnects
        reconnects += 1
        new_sess = AsyncMock()
        new_sess.receive = _empty_receive
        client._session = new_sess
        if reconnects >= 2:
            raise asyncio.CancelledError()

    with patch.object(client, "close", new_callable=AsyncMock), \
         patch.object(client, "connect", side_effect=mock_connect):
        await client.handle_messages()

    assert client._session_version == 1  # incremented only on successful reconnect


@pytest.mark.asyncio
async def test_handle_messages_exits_on_receive_exception(client):
    """Exception from receive() triggers break, not infinite retry."""
    async def broken_receive():
        raise RuntimeError("network error")
        yield  # pragma: no cover

    client._session.receive = broken_receive

    with patch.object(client, "close", new_callable=AsyncMock):
        await client.handle_messages()  # must complete without raising


@pytest.mark.asyncio
async def test_handle_messages_cancel_stops_loop(client):
    """Task cancellation exits the loop; connect() is not called."""
    async def infinite_receive():
        await asyncio.sleep(100)
        yield  # pragma: no cover

    client._session.receive = infinite_receive

    with patch.object(client, "close", new_callable=AsyncMock), \
         patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
        task = asyncio.create_task(client.handle_messages())
        await asyncio.sleep(0)  # let the task start
        task.cancel()
        await task  # CancelledError caught internally — task finishes normally

    mock_connect.assert_not_awaited()


# ---------------------------------------------------------------------------
# replay_audio_buffer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replay_audio_buffer_sends_all_chunks(client):
    """All chunks in the rolling buffer must be sent to the new session."""
    import time
    now = time.monotonic()
    client._audio_rolling_buffer.append((now, b"\x01" * 32))
    client._audio_rolling_buffer.append((now, b"\x02" * 32))

    await client.replay_audio_buffer()

    assert client._session.send_realtime_input.await_count == 2


@pytest.mark.asyncio
async def test_replay_audio_buffer_clears_buffer_after_replay(client):
    import time
    now = time.monotonic()
    client._audio_rolling_buffer.append((now, b"\x00" * 32))

    await client.replay_audio_buffer()

    assert len(client._audio_rolling_buffer) == 0


@pytest.mark.asyncio
async def test_replay_audio_buffer_noop_when_buffer_empty(client):
    await client.replay_audio_buffer()

    client._session.send_realtime_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_audio_buffer_noop_when_session_none(client):
    import time
    client._audio_rolling_buffer.append((time.monotonic(), b"\x00" * 32))
    client._session = None

    await client.replay_audio_buffer()  # must not raise


@pytest.mark.asyncio
async def test_handle_messages_processes_messages_before_reconnect(client):
    """Messages received before server close must be dispatched."""
    msg = _make_server_msg()
    processed = []

    async def receive_with_one_msg():
        yield msg

    client._session.receive = receive_with_one_msg

    original_handler = client.server_event_handler.handle_event

    async def capture_event(response):
        processed.append(response)

    client.server_event_handler.handle_event = capture_event

    with patch.object(client, "close", new_callable=AsyncMock), \
         patch.object(client, "connect", side_effect=asyncio.CancelledError):
        await client.handle_messages()

    assert msg in processed
