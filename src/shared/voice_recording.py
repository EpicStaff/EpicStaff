"""Voice-call duration ceiling and recording size limit, shared by realtime and django_app.

realtime ends a call at the ceiling and stops buffering a direction's audio at the limit;
django_app refuses a recording file above the limit. Both read the ceiling from the same
variable and derive the limit with the same function, so the size realtime writes and the
size django_app accepts cannot drift apart.
"""

import math
import struct

from src.shared.envtools import Env

MAX_CALL_DURATION_VARIABLE = "REALTIME_MAX_CALL_DURATION"

# A Twilio media stream is µ-law, 8 kHz, mono: one byte per sample.
RECORDING_AUDIO_BYTES_PER_SECOND = 8000

# Outbound audio also keeps provider audio that an interruption cleared from playback, so a
# direction can hold more audio than the call's wall-clock duration.
RECORDING_SIZE_MARGIN = 1.5

# The canonical WAV header realtime writes before a recording's µ-law audio. It lives here
# because the size limit counts it: the audio realtime may buffer is the limit minus the header.
WAV_HEADER_FORMAT = "<4sI4s4sIHHIIHH4sI"
WAV_HEADER_BYTES = struct.calcsize(WAV_HEADER_FORMAT)


def load_max_call_duration_seconds(env: Env) -> float:
    """Read the longest a voice call may last, in seconds.

    Raises:
        EnvironmentNotFoundError: The variable is not set.
        ValueError: The variable is not a finite duration, is `none`, or is too short for
            a recording to hold any audio after its WAV header. A call needs a ceiling: it
            bounds both provider cost and recording size.
    """
    message = (
        f"{MAX_CALL_DURATION_VARIABLE} must be a finite duration long enough to record "
        "audio, such as 30m."
    )
    try:
        seconds = env.time(MAX_CALL_DURATION_VARIABLE)
    except ValueError as error:
        raise ValueError(message) from error
    # to_time() parses with float(), which accepts "inf" and "nan".
    if seconds is None or not math.isfinite(seconds):
        raise ValueError(message)
    if max_recording_bytes(seconds) <= WAV_HEADER_BYTES:
        raise ValueError(message)
    return seconds


def max_recording_bytes(max_call_duration_seconds: float) -> int:
    """Return the largest recording file, WAV header included, for one call direction."""
    return int(max_call_duration_seconds * RECORDING_AUDIO_BYTES_PER_SECOND * RECORDING_SIZE_MARGIN)
