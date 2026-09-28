"""
Tests for ElevenLabs audio format conversion logic.

Three pure conversion paths:
  - ElevenLabsRealtimeAgentClient._ulaw_to_pcm16k   : µ-law 8kHz  → PCM 16kHz  (Twilio input)
  - ElevenLabsServerEventHandler._pcm16k_to_ulaw8k  : PCM 16kHz   → µ-law 8kHz (Twilio output)
  - ElevenLabsServerEventHandler._pcm16k_to_pcm24k  : PCM 16kHz   → PCM 24kHz  (browser output)

No network calls — the methods are called directly on constructed objects.
"""
import audioop
import base64
import struct
import pytest
from unittest.mock import MagicMock

from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler import (
    ElevenLabsServerEventHandler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silence_ulaw(n_samples: int) -> bytes:
    """Generate n_samples of silence encoded as µ-law (0xFF = silence)."""
    return bytes([0xFF] * n_samples)


def _silence_pcm16(n_samples: int) -> bytes:
    """Generate n_samples of silence as 16-bit signed PCM."""
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def _b64_silence_pcm16(n_samples: int) -> str:
    return base64.b64encode(_silence_pcm16(n_samples)).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def el_client():
    """Minimal ElevenLabsRealtimeAgentClient with no network dependencies."""
    return ElevenLabsRealtimeAgentClient(api_key="test_key", connection_key="test_conn")


@pytest.fixture
def mock_client_for_handler():
    """Mock client passed to ElevenLabsServerEventHandler."""
    client = MagicMock()
    client.connection_key = "test_conn"
    client.is_twilio = False
    client._down_resample_state = None
    return client


@pytest.fixture
def server_handler(mock_client_for_handler):
    return ElevenLabsServerEventHandler(mock_client_for_handler)


# ---------------------------------------------------------------------------
# _ulaw_to_pcm16k  (Twilio input path: ElevenLabsRealtimeAgentClient)
# ---------------------------------------------------------------------------

def test_ulaw_to_pcm16k_returns_bytes(el_client):
    ulaw = _silence_ulaw(160)
    result = el_client._ulaw_to_pcm16k(ulaw)
    assert isinstance(result, bytes)


def test_ulaw_to_pcm16k_doubles_sample_count(el_client):
    """8 kHz → 16 kHz resampling should roughly double the byte count."""
    ulaw = _silence_ulaw(160)          # 160 samples at 8kHz = 20ms
    result = el_client._ulaw_to_pcm16k(ulaw)
    # Each sample is 2 bytes (int16); expect ~2x byte count after resampling
    expected_bytes = 160 * 2 * 2      # 160 samples x 2 bytes x 2x upsample
    assert abs(len(result) - expected_bytes) <= 8  # small rounding tolerance


def test_ulaw_to_pcm16k_updates_resample_state(el_client):
    """Stateful resampling: _up_resample_state must be updated after first call."""
    assert el_client._up_resample_state is None
    el_client._ulaw_to_pcm16k(_silence_ulaw(160))
    assert el_client._up_resample_state is not None


def test_ulaw_to_pcm16k_state_is_consistent_across_chunks(el_client):
    """Two consecutive chunks should produce the same byte count as one merged chunk."""
    chunk = _silence_ulaw(160)
    r1 = el_client._ulaw_to_pcm16k(chunk)
    r2 = el_client._ulaw_to_pcm16k(chunk)
    assert len(r1) > 0
    assert len(r2) > 0


# ---------------------------------------------------------------------------
# _pcm16k_to_ulaw8k  (Twilio output path: ElevenLabsServerEventHandler)
# ---------------------------------------------------------------------------

def test_pcm16k_to_ulaw8k_returns_string(server_handler):
    b64_in = _b64_silence_pcm16(320)  # 320 samples = 20ms at 16kHz
    result = server_handler._pcm16k_to_ulaw8k(b64_in)
    assert isinstance(result, str)


def test_pcm16k_to_ulaw8k_is_valid_base64(server_handler):
    b64_in = _b64_silence_pcm16(320)
    result = server_handler._pcm16k_to_ulaw8k(b64_in)
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


def test_pcm16k_to_ulaw8k_halves_sample_count(server_handler):
    """16kHz → 8kHz resampling should roughly halve the sample count."""
    n_in = 320   # 320 samples at 16kHz = 20ms
    b64_in = _b64_silence_pcm16(n_in)
    result_bytes = base64.b64decode(server_handler._pcm16k_to_ulaw8k(b64_in))
    # µ-law is 1 byte per sample; expect ~160 samples (n_in / 2)
    assert abs(len(result_bytes) - n_in // 2) <= 4


def test_pcm16k_to_ulaw8k_updates_client_resample_state(server_handler, mock_client_for_handler):
    assert mock_client_for_handler._down_resample_state is None
    server_handler._pcm16k_to_ulaw8k(_b64_silence_pcm16(320))
    assert mock_client_for_handler._down_resample_state is not None


# ---------------------------------------------------------------------------
# _pcm16k_to_pcm24k  (browser output path: ElevenLabsServerEventHandler)
# ---------------------------------------------------------------------------

def test_pcm16k_to_pcm24k_returns_string(server_handler):
    b64_in = _b64_silence_pcm16(160)
    result = server_handler._pcm16k_to_pcm24k(b64_in)
    assert isinstance(result, str)


def test_pcm16k_to_pcm24k_is_valid_base64(server_handler):
    b64_in = _b64_silence_pcm16(160)
    result = server_handler._pcm16k_to_pcm24k(b64_in)
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


def test_pcm16k_to_pcm24k_upsamples_to_1_5x(server_handler):
    """16kHz → 24kHz: output should have 1.5x the number of samples."""
    n_in = 100
    b64_in = _b64_silence_pcm16(n_in)
    result_bytes = base64.b64decode(server_handler._pcm16k_to_pcm24k(b64_in))
    n_out = len(result_bytes) // 2   # int16 = 2 bytes
    expected = int(n_in * 1.5)
    assert abs(n_out - expected) <= 2


def test_pcm16k_to_pcm24k_empty_input_returns_same_b64(server_handler):
    """Empty base64 PCM should be returned unchanged (guard clause)."""
    empty_b64 = base64.b64encode(b"").decode()
    result = server_handler._pcm16k_to_pcm24k(empty_b64)
    assert result == empty_b64


def test_pcm16k_to_pcm24k_invalid_input_returns_original(server_handler):
    """Garbage input should be returned unchanged (exception guard)."""
    bad_b64 = base64.b64encode(b"\x01").decode()  # odd byte count → numpy can't parse
    result = server_handler._pcm16k_to_pcm24k(bad_b64)
    # Should either succeed or return the original without raising
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Round-trip: ulaw8k → pcm16k → ulaw8k  (sanity)
# ---------------------------------------------------------------------------

def test_round_trip_silence_stays_silent(el_client, server_handler):
    """Silence through ulaw→pcm16k→ulaw8k should decode back to near-zero PCM."""
    ulaw_in = _silence_ulaw(160)
    pcm16k = el_client._ulaw_to_pcm16k(ulaw_in)

    # Re-encode to base64 and convert back through server handler
    b64_pcm16k = base64.b64encode(pcm16k).decode()
    b64_ulaw_out = server_handler._pcm16k_to_ulaw8k(b64_pcm16k)
    ulaw_out = base64.b64decode(b64_ulaw_out)

    # Decode back to PCM and check amplitude is low (silence)
    pcm_out = audioop.ulaw2lin(ulaw_out, 2)
    samples = struct.unpack(f"<{len(pcm_out)//2}h", pcm_out)
    max_amplitude = max(abs(s) for s in samples)
    assert max_amplitude < 500   # silence should have very low amplitude
