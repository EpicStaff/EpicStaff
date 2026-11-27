"""A recording cut at realtime's cap is exactly the file size django_app accepts.

Both services read MAX_VOICE_RECORDING_SIZE; realtime leaves room for the WAV header
that `_build_ulaw_wav` writes, since django_app limits the whole file.
"""

from application.voice_call_service import _build_ulaw_wav
from core import config


def test_the_largest_recording_is_exactly_the_size_django_app_accepts():
    wav = _build_ulaw_wav(b"\x00" * config.MAX_RECORDING_AUDIO_BYTES)

    assert len(wav) == config.MAX_VOICE_RECORDING_SIZE
