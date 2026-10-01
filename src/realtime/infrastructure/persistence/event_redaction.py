"""Decide what part of a realtime event is allowed to reach the database.

Session items are a conversation record, not a recording: raw audio frames are
never stored, because they carry the end user's (and the model's) voice and
arrive at tens per second.
"""

import re
from typing import Any

AUDIO_REDACTED = "[audio redacted]"

# Events whose whole payload is one audio frame. Nothing is left once the audio
# is removed, so no row is written for them.
_AUDIO_FRAME_EVENT_TYPES = frozenset(
    {
        "input_audio_buffer.append",
        "response.audio.delta",
        "response.output_audio.delta",
        "audio",  # ElevenLabs
    }
)

# Keys that hold base64 audio when their value is a string. `audio` is also the
# name of a config dict inside `session.update`, which is not audio and is kept.
_AUDIO_KEYS = frozenset({"audio", "audio_base_64", "audio_base64"})

# Gemini events are persisted as `str(response)`, where audio appears as the repr
# of a bytes literal: `data=b'...'`. A bytes repr escapes its own quote character,
# so the first unescaped matching quote ends the literal. The two alternatives in
# each group are mutually exclusive (one excludes the backslash the other starts
# with), which keeps matching linear: attacker-shaped text must not cause
# catastrophic backtracking on the event loop.
_BYTES_LITERAL = re.compile(r"""data=b(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""", re.DOTALL)
_GEMINI_EVENT_TYPE = "gemini_event"


def redact_event_for_storage(event: Any) -> Any:
    """Return a copy of `event` safe to persist, or None if it must not be stored.

    Args:
        event: The realtime event exactly as received or sent.

    Returns:
        The event with audio payloads replaced by a placeholder, or None for events
        that consist only of an audio frame.
    """
    if isinstance(event, dict) and event.get("type") in _AUDIO_FRAME_EVENT_TYPES:
        return None
    redacted = _redact(event)
    # Only Gemini's stringified response is scrubbed by pattern; running the regex
    # over every string would apply it to user-controlled text for no benefit.
    if (
        isinstance(redacted, dict)
        and redacted.get("type") == _GEMINI_EVENT_TYPE
        and isinstance(redacted.get("raw"), str)
    ):
        redacted["raw"] = _BYTES_LITERAL.sub(f"data={AUDIO_REDACTED}", redacted["raw"])
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: AUDIO_REDACTED if key in _AUDIO_KEYS and isinstance(item, str) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
