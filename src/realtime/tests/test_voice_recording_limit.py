"""The call-duration ceiling sizes the recordings, and realtime and django_app agree on it.

realtime stops a direction's audio at MAX_RECORDING_AUDIO_BYTES; django_app refuses a file
above max_recording_bytes(ceiling). A recording cut at realtime's cap must still be one
django_app accepts, or the whole recording is lost.
"""

import pytest

from application.voice_call_service import _build_ulaw_wav
from core import config
from src.shared.envtools import Env, EnvironmentNotFoundError
from src.shared.voice_recording import load_max_call_duration_seconds, max_recording_bytes

VARIABLE = "REALTIME_MAX_CALL_DURATION"


@pytest.mark.parametrize(("value", "expected"), [("30m", 1800.0), ("90s", 90.0), ("1", 1.0), ("0.004", 0.004)])
def test_reads_the_ceiling_in_seconds(value, expected):
    assert load_max_call_duration_seconds(Env({VARIABLE: value})) == expected


# A call needs a ceiling, and 0.003 s gives a limit (36 bytes) smaller than the WAV header.
@pytest.mark.parametrize("value", ["none", "inf", "nan", "abc", "", "0", "-1", "0.003"])
def test_rejects_a_ceiling_that_cannot_bound_a_call_or_hold_audio(value):
    with pytest.raises(ValueError, match=VARIABLE):
        load_max_call_duration_seconds(Env({VARIABLE: value}))


def test_a_missing_ceiling_names_itself():
    with pytest.raises(EnvironmentNotFoundError, match=VARIABLE):
        load_max_call_duration_seconds(Env({}))


def test_a_thirty_minute_call_allows_a_recording_of_one_and_a_half_times_its_audio():
    assert max_recording_bytes(1800) == 21_600_000


def test_a_recording_cut_at_realtimes_cap_is_exactly_the_largest_file_django_accepts():
    wav = _build_ulaw_wav(b"\x00" * config.MAX_RECORDING_AUDIO_BYTES)

    assert len(wav) == max_recording_bytes(config.MAX_CALL_DURATION_SECONDS)
