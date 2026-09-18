"""
Tests for GeminiServerEventHandler.

save_realtime_session_item_to_db is patched out to avoid DB dependency.
The genai module is patched to avoid lazy-import errors in the client type hint.
"""
import asyncio
import base64
import audioop
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from infrastructure.providers.gemini.event_handlers.gemini_server_event_handler import (
    GeminiServerEventHandler,
)

_DB_PATCH = "infrastructure.providers.gemini.event_handlers.gemini_server_event_handler.save_realtime_session_item_to_db"
_GENAI_PATCH = "infrastructure.providers.gemini.gemini_realtime_agent_client.genai"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    c = MagicMock()
    c.connection_key = "conn_test"
    c.is_twilio = False
    c.send_client = AsyncMock()
    c.call_tool = AsyncMock()
    c._resample_state_out = None
    c._conversation_history = []
    c._session = AsyncMock()
    c._session_version = 0
    return c


@pytest.fixture
def handler(client):
    with patch(_GENAI_PATCH):
        return GeminiServerEventHandler(client)


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_handle_event_forwards_org_id_to_db_write(mock_db, handler, client):
    client.org_id = 77
    response = MagicMock()
    response.setup_complete = None
    response.server_content = None
    response.tool_call = None

    await handler.handle_event(response)

    _, kwargs = mock_db.call_args
    assert kwargs.get("org_id") == 77


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _server_content(
    *,
    has_audio=False,
    has_text=False,
    turn_complete=False,
    interrupted=False,
    output_text=None,
    input_text=None,
):
    sc = MagicMock()
    sc.interrupted = interrupted
    sc.turn_complete = turn_complete

    sc.model_turn = None
    if has_audio or has_text:
        part = MagicMock()
        if has_audio:
            part.inline_data = MagicMock()
            part.inline_data.data = b"\x00\x01" * 100
            part.text = None
        else:
            part.inline_data = None
            part.text = "hello"
        sc.model_turn = MagicMock()
        sc.model_turn.parts = [part]

    sc.output_transcription = MagicMock()
    sc.output_transcription.text = output_text or ""
    sc.input_transcription = MagicMock()
    sc.input_transcription.text = input_text or ""
    return sc


def _make_response(*, server_content=None, setup_complete=None, tool_call=None):
    r = MagicMock()
    r.setup_complete = setup_complete
    r.server_content = server_content
    r.tool_call = tool_call
    return r


# ---------------------------------------------------------------------------
# setup_complete → session.created event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_setup_complete_sends_session_created(mock_db, handler, client):
    response = _make_response(setup_complete=MagicMock())
    await handler.handle_event(response)
    client.send_client.assert_awaited_once()
    event = client.send_client.call_args[0][0]
    assert event["type"] == "session.created"


# ---------------------------------------------------------------------------
# server_content — audio part → response.audio.delta
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_audio_part_sends_audio_delta(mock_db, handler, client):
    client.is_twilio = False
    sc = _server_content(has_audio=True)
    await handler.handle_event(_make_response(server_content=sc))

    sent = [
        call[0][0] for call in client.send_client.call_args_list
        if call[0][0].get("type") == "response.audio.delta"
    ]
    assert len(sent) == 1


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_audio_part_twilio_converts_to_ulaw(mock_db, handler, client):
    """Twilio path: PCM 24kHz → µ-law 8kHz conversion must happen."""
    client.is_twilio = True
    pcm_24k = b"\x00\x00" * 240  # 240 16-bit samples

    sc = MagicMock()
    sc.interrupted = False
    sc.turn_complete = False
    sc.output_transcription = MagicMock()
    sc.output_transcription.text = ""
    sc.input_transcription = MagicMock()
    sc.input_transcription.text = ""

    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = pcm_24k
    part.text = None
    sc.model_turn = MagicMock()
    sc.model_turn.parts = [part]

    await handler.handle_event(_make_response(server_content=sc))

    deltas = [
        c[0][0] for c in client.send_client.call_args_list
        if c[0][0].get("type") == "response.audio.delta"
    ]
    assert len(deltas) == 1
    # Twilio expects base64-encoded µ-law — just verify it's non-empty base64
    payload = deltas[0]["delta"]
    assert len(base64.b64decode(payload)) > 0


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_audio_part_browser_passes_pcm_through(mock_db, handler, client):
    """Browser path: raw PCM must be base64-encoded as-is (no conversion)."""
    client.is_twilio = False
    pcm = b"\x01\x02" * 50

    sc = MagicMock()
    sc.interrupted = False
    sc.turn_complete = False
    sc.output_transcription = MagicMock()
    sc.output_transcription.text = ""
    sc.input_transcription = MagicMock()
    sc.input_transcription.text = ""

    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = pcm
    part.text = None
    sc.model_turn = MagicMock()
    sc.model_turn.parts = [part]

    await handler.handle_event(_make_response(server_content=sc))

    deltas = [
        c[0][0] for c in client.send_client.call_args_list
        if c[0][0].get("type") == "response.audio.delta"
    ]
    assert len(deltas) == 1
    assert base64.b64decode(deltas[0]["delta"]) == pcm


# ---------------------------------------------------------------------------
# server_content — turn_complete → history + done events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_turn_complete_saves_transcript_to_history(mock_db, handler, client):
    handler._current_response_id = "resp_1"
    handler._current_item_id = "item_1"
    handler._current_transcript = "Hello world"

    sc = _server_content(turn_complete=True)
    await handler.handle_event(_make_response(server_content=sc))

    assert any(
        e.get("role") == "model" and "Hello world" in e.get("text", "")
        for e in client._conversation_history
    )


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_turn_complete_resets_state(mock_db, handler, client):
    handler._current_response_id = "r"
    handler._current_item_id = "i"
    handler._current_transcript = "some text"

    sc = _server_content(turn_complete=True)
    await handler.handle_event(_make_response(server_content=sc))

    assert handler._current_response_id is None
    assert handler._current_item_id is None
    assert handler._current_transcript == ""


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_turn_complete_sends_response_done(mock_db, handler, client):
    handler._current_response_id = "resp_1"
    handler._current_item_id = "item_1"

    sc = _server_content(turn_complete=True)
    await handler.handle_event(_make_response(server_content=sc))

    types_sent = {c[0][0]["type"] for c in client.send_client.call_args_list}
    assert "response.done" in types_sent


# ---------------------------------------------------------------------------
# server_content — input_transcription → user history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_input_transcription_saves_user_history(mock_db, handler, client):
    sc = _server_content(input_text="user said this")
    await handler.handle_event(_make_response(server_content=sc))

    assert any(
        e.get("role") == "user" and "user said this" in e.get("text", "")
        for e in client._conversation_history
    )


# ---------------------------------------------------------------------------
# server_content — interrupted → clear state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_interrupted_clears_current_response(mock_db, handler, client):
    handler._current_response_id = "resp_active"
    handler._current_item_id = "item_active"

    sc = _server_content(interrupted=True)
    await handler.handle_event(_make_response(server_content=sc))

    assert handler._current_response_id is None
    assert handler._current_item_id is None


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_interrupted_sends_speech_started_event(mock_db, handler, client):
    handler._current_response_id = "r1"
    sc = _server_content(interrupted=True)
    await handler.handle_event(_make_response(server_content=sc))

    types_sent = [c[0][0]["type"] for c in client.send_client.call_args_list]
    assert "input_audio_buffer.speech_started" in types_sent


# ---------------------------------------------------------------------------
# tool_call → call_tool spawned as background task (non-blocking)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_tool_call_is_non_blocking(mock_db, handler, client):
    """call_tool must run as background task — _handle_tool_call must return quickly."""
    call_started = asyncio.Event()
    call_done = asyncio.Event()

    async def slow_call_tool(*args, **kwargs):
        call_started.set()
        await asyncio.sleep(10)  # simulate long-running tool
        call_done.set()

    client.call_tool = slow_call_tool

    func = MagicMock()
    func.id = "cid"
    func.name = "slow_tool"
    func.args = {}
    tool_call = MagicMock()
    tool_call.function_calls = [func]

    import time
    start = time.monotonic()
    await handler._handle_tool_call(tool_call)
    elapsed = time.monotonic() - start

    # Yield to event loop so the background task can start executing
    await asyncio.sleep(0)

    assert elapsed < 0.5, "Tool call must not block the event handler"
    assert call_started.is_set(), "Task should have been started"
    assert not call_done.is_set(), "Task should still be running"

    # Cleanup: let the task detect cancellation
    await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()},
                         return_exceptions=True)


@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_tool_call_sends_function_call_events(mock_db, handler, client):
    """handle_event with tool_call must emit conversation.item.created."""
    func = MagicMock()
    func.id = "c1"
    func.name = "my_tool"
    func.args = {"x": 1}
    tool_call = MagicMock()
    tool_call.function_calls = [func]

    response = _make_response(tool_call=tool_call)
    await handler.handle_event(response)

    types_sent = [c[0][0]["type"] for c in client.send_client.call_args_list]
    assert "conversation.item.created" in types_sent


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

def test_reset_clears_all_state(handler):
    handler._current_response_id = "r"
    handler._current_item_id = "i"
    handler._current_user_item_id = "u"
    handler._current_output_index = 5
    handler._assistant_output_index = 3
    handler._current_transcript = "some text"
    handler._discarding_audio = True

    handler.reset()

    assert handler._current_response_id is None
    assert handler._current_item_id is None
    assert handler._current_user_item_id is None
    assert handler._current_output_index == 0
    assert handler._assistant_output_index == 0
    assert handler._current_transcript == ""
    assert handler._discarding_audio is False


# ---------------------------------------------------------------------------
# save_realtime_session_item_to_db is always called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch(_DB_PATCH, new_callable=AsyncMock)
async def test_db_save_called_for_every_event(mock_db, handler):
    response = _make_response()
    await handler.handle_event(response)
    mock_db.assert_awaited_once()
