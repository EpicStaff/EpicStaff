"""ElevenLabs audio formats on a Twilio call: caller µ-law 8 kHz goes up as PCM 16 kHz,
and the agent's PCM 16 kHz comes back as µ-law 8 kHz.

The provider websocket (`send_server`) and the frontend side (`send_client`) are recorders.
"""

import audioop
import base64
import struct
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import ElevenLabsRealtimeAgentClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    client = ElevenLabsRealtimeAgentClient(api_key="test_key", connection_key="test_conn")
    client.send_server = AsyncMock()
    client.send_client = AsyncMock()
    client.is_twilio = True
    return client


def _tone(samples: int) -> bytes:
    return struct.pack(f"<{samples}h", *[(index % 50) * 400 - 10000 for index in range(samples)])


async def _upload(client, ulaw: bytes) -> bytes:
    client.send_server.reset_mock()
    await client.send_audio(base64.b64encode(ulaw).decode())
    (call,) = client.send_server.await_args_list
    return base64.b64decode(call.args[0]["user_audio_chunk"])


async def test_caller_audio_is_sent_as_16k_pcm_continuously_across_chunks(client):
    ulaw = audioop.lin2ulaw(_tone(320), 2)
    whole = ElevenLabsRealtimeAgentClient(api_key="k", connection_key="c")
    whole.send_server = AsyncMock()

    halves = await _upload(client, ulaw[:160]) + await _upload(client, ulaw[160:])

    # 320 samples at 8 kHz are about 640 at 16 kHz; resampling state carries across
    # chunks, so a stream split into frames sounds the same as one long frame.
    assert len(halves) // 2 == pytest.approx(640, abs=4)
    assert halves == await _upload(whole, ulaw)


async def test_agent_audio_round_trip_keeps_silence_silent(client):
    pcm16k = await _upload(client, b"\xff" * 160)

    with patch(
        "infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db",
        new_callable=AsyncMock,
    ):
        await client.server_event_handler.handle_event(
            {"type": "audio", "audio_event": {"audio_base_64": base64.b64encode(pcm16k).decode()}}
        )

    delta = next(call.args[0] for call in client.send_client.await_args_list if call.args[0]["type"] == "response.audio.delta")
    pcm_out = audioop.ulaw2lin(base64.b64decode(delta["delta"]), 2)
    assert max(abs(sample) for sample in struct.unpack(f"<{len(pcm_out) // 2}h", pcm_out)) < 500


async def test_unreadable_browser_audio_is_passed_on_rather_than_dropped(client):
    """An odd byte count can't be read as 16-bit PCM; the frame is forwarded unchanged."""
    client.is_twilio = False
    odd = base64.b64encode(b"\x01").decode()

    with patch(
        "infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler.save_realtime_session_item_to_db",
        new_callable=AsyncMock,
    ):
        await client.server_event_handler.handle_event({"type": "audio", "audio_event": {"audio_base_64": odd}})

    delta = next(call.args[0] for call in client.send_client.await_args_list if call.args[0]["type"] == "response.audio.delta")
    assert delta["delta"] == odd
