from __future__ import annotations

"""
Minimal partial-JSON helpers for streaming JSON responses.

These helpers are used by ``FlowAssistantService.stream_reply`` to extract
the ``message`` field value incrementally from the LLM's streamed JSON output
as tokens arrive, before the full document is complete.

Examples
--------
>>> extract_message_field('')
''
>>> extract_message_field('{"message": "he')
'he'
>>> extract_message_field('{"message": "hello"}')
'hello'
>>> extract_message_field('{"message": "hi\\nthere"}')
'hi\\nthere'
>>> extract_message_field('{"message": "with \\"quote\\""}')
'with "quote"'
>>> extract_message_field('{"message": "done", "ef_tables": []}')
'done'
>>> extract_message_field('{"ef_tables": []}')
''
"""

import enum
import json
import re

_MESSAGE_KEY = '"message"'
_JSON_WHITESPACE = " \t\r\n"
# The characters that interrupt a run of literal text inside a JSON string.
_STRING_SPECIAL_CHARACTER = re.compile(r'["\\]')
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
}
# A ``\uXXXX`` escape is six characters long.
_UNICODE_ESCAPE_LENGTH = 6


class _Phase(enum.Enum):
    SEEKING_KEY = enum.auto()
    SEEKING_COLON = enum.auto()
    SEEKING_OPENING_QUOTE = enum.auto()
    IN_STRING = enum.auto()
    DONE = enum.auto()


class MessageFieldStream:
    """Decode the ``"message"`` string value of a JSON document fed in chunks.

    Each ``feed`` call returns only the part of the value decoded from the new
    chunk, so a whole document costs work proportional to its length.  Only the
    unconsumed tail is kept between calls: up to ``len('"message"') - 1``
    characters while the key may still be split across chunks, or an escape
    sequence (a lone ``\\`` or a partial ``\\uXXXX``) cut by the end of a chunk.

    The key is found by plain substring search: the risk of a false positive on
    a value containing ``"message"`` is accepted in exchange for simplicity.
    The LLM follows the schema; the key appears exactly once.  Only the first
    occurrence is considered — when it is not followed by ``:`` and a string,
    the stream yields nothing more.  Everything after the closing quote is
    ignored.
    """

    def __init__(self) -> None:
        self._phase = _Phase.SEEKING_KEY
        self._pending = ""

    def feed(self, chunk: str) -> str:
        """Consume ``chunk`` and return the newly decoded part of the message value."""
        if self._phase is _Phase.DONE:
            return ""
        text = self._pending + chunk
        self._pending = ""
        position = 0

        if self._phase is _Phase.SEEKING_KEY:
            key_position = text.find(_MESSAGE_KEY)
            if key_position == -1:
                # Keep a tail long enough to hold a key cut by the chunk boundary.
                self._pending = text[-(len(_MESSAGE_KEY) - 1) :]
                return ""
            position = key_position + len(_MESSAGE_KEY)
            self._phase = _Phase.SEEKING_COLON

        if self._phase is _Phase.SEEKING_COLON:
            position = self._skip_whitespace(text, position)
            if position == len(text):
                return ""
            if text[position] != ":":
                self._phase = _Phase.DONE
                return ""
            position += 1
            self._phase = _Phase.SEEKING_OPENING_QUOTE

        if self._phase is _Phase.SEEKING_OPENING_QUOTE:
            position = self._skip_whitespace(text, position)
            if position == len(text):
                return ""
            if text[position] != '"':
                self._phase = _Phase.DONE
                return ""
            position += 1
            self._phase = _Phase.IN_STRING

        return self._decode_string(text, position)

    @staticmethod
    def _skip_whitespace(text: str, position: int) -> int:
        while position < len(text) and text[position] in _JSON_WHITESPACE:
            position += 1
        return position

    def _decode_string(self, text: str, position: int) -> str:
        decoded: list[str] = []
        while position < len(text):
            match = _STRING_SPECIAL_CHARACTER.search(text, position)
            if match is None:
                decoded.append(text[position:])
                break
            special_position = match.start()
            decoded.append(text[position:special_position])
            if text[special_position] == '"':
                self._phase = _Phase.DONE
                break
            position = self._decode_escape(text, special_position, decoded)
            if position == -1:
                # Incomplete escape at the end of the chunk: wait for the rest.
                self._pending = text[special_position:]
                break
        return "".join(decoded)

    @staticmethod
    def _decode_escape(text: str, backslash_position: int, decoded: list[str]) -> int:
        """Append the escape at ``backslash_position`` and return the position after it.

        Returns ``-1`` when the escape is cut by the end of ``text``.
        """
        if backslash_position + 1 >= len(text):
            return -1
        escape = text[backslash_position + 1]
        if escape != "u":
            # An unknown escape is emitted literally.
            decoded.append(_SIMPLE_ESCAPES.get(escape, escape))
            return backslash_position + 2
        escape_end = backslash_position + _UNICODE_ESCAPE_LENGTH
        if escape_end > len(text):
            return -1
        hex_digits = text[backslash_position + 2 : escape_end]
        try:
            decoded.append(chr(int(hex_digits, 16)))
        except ValueError:
            # A malformed escape is emitted as-is.
            decoded.append(f"\\u{hex_digits}")
        return escape_end


def extract_message_field(buffer: str) -> str:
    """Return the ``"message"`` value decoded so far from a partial JSON string.

    Returns ``""`` when the key, its colon or its opening quote has not arrived
    yet.  See ``MessageFieldStream`` for the parsing rules; use it instead when
    the document arrives in chunks.
    """
    return MessageFieldStream().feed(buffer)


def try_parse_full(buffer: str) -> dict | None:
    """Attempt to parse ``buffer`` as complete JSON.

    Strict first: when ``buffer`` is valid JSON as a whole, the parsed ``dict``
    is returned as-is (with or without a ``message`` key).

    Lenient fallback for models that ignore ``response_format``: the first JSON
    object is decoded from the first ``{`` onward, so a surrounding markdown
    code fence (```` ```json ````) or prose before / after it is ignored.  The
    lenient result is accepted only when it is a ``dict`` whose ``message`` is
    a string, so arbitrary JSON embedded in prose is not mistaken for the
    structured reply.

    Returns ``None`` when neither attempt yields a ``dict`` — including
    truncated JSON (the stream is still in progress or was cut off); cancel and
    disconnect paths rely on that.

    Used at end-of-stream to obtain the full structured payload
    (``ef_tables``, ``action_message``, canonical ``message``).
    """
    try:
        result = json.loads(buffer)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, ValueError):
        pass

    lenient_result = _decode_first_object(buffer)
    if isinstance(lenient_result, dict) and isinstance(lenient_result.get("message"), str):
        return lenient_result
    return None


def _decode_first_object(text: str) -> object | None:
    object_start = text.find("{")
    if object_start == -1:
        return None
    try:
        decoded, _ = json.JSONDecoder().raw_decode(text, object_start)
    except (json.JSONDecodeError, ValueError):
        return None
    return decoded
