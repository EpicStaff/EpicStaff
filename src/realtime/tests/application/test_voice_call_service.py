import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi import WebSocket
from src.shared.models import RealtimeAgentChatData
from domain.ports.i_realtime_agent_client import IRealtimeAgentClient
from application.voice_call_service import VoiceCallService, MIN_CHUNK_SIZE


def _make_chat_data() -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key="test_key",
        org_id=1,
        rt_api_key="api_key",
        rt_model_name="gpt-4o",
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
        tools=[],
        llm=None,
    )


@pytest.fixture
def twilio_ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.iter_text = AsyncMock(return_value=iter([]))
    return ws


@pytest.fixture
def rt_client():
    client = AsyncMock(spec=IRealtimeAgentClient)
    client.stream_sid = None
    client.is_twilio = True
    return client


@pytest.fixture
def service(twilio_ws):
    return VoiceCallService(
        twilio_ws=twilio_ws,
        realtime_agent_chat_data=_make_chat_data(),
        instructions="You are a helpful assistant",
        tool_manager_service=MagicMock(),
        connections={},
        factory=MagicMock(),
        initial_message=None,
    )


# ---------------------------------------------------------------------------
# _handle_twilio_message — start event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_event_sets_stream_sid(service, rt_client):
    await service._handle_twilio_message(
        {"event": "start", "start": {"streamSid": "MZ123"}},
        rt_client,
    )
    assert service.stream_sid == "MZ123"


@pytest.mark.asyncio
async def test_start_event_sets_client_stream_sid(service, rt_client):
    await service._handle_twilio_message(
        {"event": "start", "start": {"streamSid": "MZ456"}},
        rt_client,
    )
    assert rt_client.stream_sid == "MZ456"


@pytest.mark.asyncio
async def test_start_event_calls_on_stream_start(service, rt_client):
    await service._handle_twilio_message(
        {"event": "start", "start": {"streamSid": "MZ789"}},
        rt_client,
    )
    rt_client.on_stream_start.assert_awaited_once()


# ---------------------------------------------------------------------------
# _handle_twilio_message — media event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_event_accumulates_audio(service, rt_client):
    raw_bytes = b"\x00\x01\x02"
    payload = base64.b64encode(raw_bytes).decode()
    await service._handle_twilio_message(
        {"event": "media", "media": {"payload": payload}},
        rt_client,
    )
    assert bytes(service.audio_accumulator) == raw_bytes


@pytest.mark.asyncio
async def test_media_event_accumulates_across_multiple_messages(service, rt_client):
    chunk = b"\xff" * 100
    payload = base64.b64encode(chunk).decode()
    # Send multiple small chunks — none should flush yet
    for _ in range(5):
        await service._handle_twilio_message(
            {"event": "media", "media": {"payload": payload}},
            rt_client,
        )
    assert len(service.audio_accumulator) == 500
    rt_client.send_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_flushes_when_threshold_reached(service, rt_client):
    # One chunk of exactly MIN_CHUNK_SIZE bytes triggers a flush
    big_chunk = b"\xaa" * MIN_CHUNK_SIZE
    payload = base64.b64encode(big_chunk).decode()
    await service._handle_twilio_message(
        {"event": "media", "media": {"payload": payload}},
        rt_client,
    )
    rt_client.send_audio.assert_awaited_once()
    # accumulator cleared after flush
    assert len(service.audio_accumulator) == 0


# ---------------------------------------------------------------------------
# _flush_audio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_audio_sends_b64_encoded_audio(service, rt_client):
    service.audio_accumulator.extend(b"\x01\x02\x03")
    await service._flush_audio(rt_client)
    expected_b64 = base64.b64encode(b"\x01\x02\x03").decode()
    rt_client.send_audio.assert_awaited_once_with(expected_b64)


@pytest.mark.asyncio
async def test_flush_audio_clears_accumulator(service, rt_client):
    service.audio_accumulator.extend(b"\x01\x02\x03")
    await service._flush_audio(rt_client)
    assert len(service.audio_accumulator) == 0


@pytest.mark.asyncio
async def test_flush_audio_noop_when_empty(service, rt_client):
    await service._flush_audio(rt_client)
    rt_client.send_audio.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_provider_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_event_audio_delta_sends_to_twilio(service, twilio_ws):
    service.stream_sid = "MZ123"
    audio = b"\xaa\xbb\xcc"
    delta_b64 = base64.b64encode(audio).decode()
    await service._handle_provider_event({"type": "response.audio.delta", "delta": delta_b64})
    twilio_ws.send_json.assert_awaited_once()
    call_kwargs = twilio_ws.send_json.call_args[0][0]
    assert call_kwargs["event"] == "media"
    assert call_kwargs["streamSid"] == "MZ123"


@pytest.mark.asyncio
async def test_provider_event_interruption_sends_clear(service, twilio_ws):
    service.stream_sid = "MZ123"
    await service._handle_provider_event({"type": "interruption"})
    twilio_ws.send_json.assert_awaited_once()
    call_kwargs = twilio_ws.send_json.call_args[0][0]
    assert call_kwargs["event"] == "clear"
    assert call_kwargs["streamSid"] == "MZ123"


@pytest.mark.asyncio
async def test_provider_event_speech_started_sends_clear(service, twilio_ws):
    service.stream_sid = "MZ123"
    await service._handle_provider_event({"type": "input_audio_buffer.speech_started"})
    twilio_ws.send_json.assert_awaited_once()
    call_kwargs = twilio_ws.send_json.call_args[0][0]
    assert call_kwargs["event"] == "clear"


@pytest.mark.asyncio
async def test_provider_event_unknown_type_does_nothing(service, twilio_ws):
    service.stream_sid = "MZ123"
    await service._handle_provider_event({"type": "unknown_event"})
    twilio_ws.send_json.assert_not_awaited()


# ---------------------------------------------------------------------------
# _send_audio_to_twilio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_audio_to_twilio_requires_stream_sid(service, twilio_ws):
    service.stream_sid = None  # no stream_sid set
    await service._send_audio_to_twilio(b"\x01\x02")
    twilio_ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_audio_to_twilio_sends_correct_payload(service, twilio_ws):
    service.stream_sid = "MZabc"
    audio = b"\xde\xad\xbe\xef"
    await service._send_audio_to_twilio(audio)
    twilio_ws.send_json.assert_awaited_once()
    payload = twilio_ws.send_json.call_args[0][0]
    assert payload["event"] == "media"
    assert payload["streamSid"] == "MZabc"
    assert payload["media"]["payload"] == base64.b64encode(audio).decode()


# ---------------------------------------------------------------------------
# _clear_twilio_buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_twilio_buffer_sends_clear_event(service, twilio_ws):
    service.stream_sid = "MZxyz"
    await service._clear_twilio_buffer()
    twilio_ws.send_json.assert_awaited_once_with(
        {"event": "clear", "streamSid": "MZxyz"}
    )


@pytest.mark.asyncio
async def test_clear_twilio_buffer_skipped_without_stream_sid(service, twilio_ws):
    service.stream_sid = None
    await service._clear_twilio_buffer()
    twilio_ws.send_json.assert_not_awaited()
