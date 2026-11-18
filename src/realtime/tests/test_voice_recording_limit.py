"""A recording cut at realtime's cap stays below the file size django_app accepts.

django_app refuses a recording above DJANGO_MAX_VOICE_RECORDING_SIZE (22mb by default, 23,068,672
bytes), and a refused recording is lost whole, so realtime must stop each direction's audio
short of it.
"""

from application.voice_call_service import _build_ulaw_wav
from core import config


def test_the_largest_recording_is_one_and_a_half_times_a_thirty_minute_call_header_included():
    wav = _build_ulaw_wav(b"\x00" * config.MAX_RECORDING_AUDIO_BYTES)

    # 1800 s x 8000 bytes/s x 1.5.
    assert len(wav) == 21_600_000
