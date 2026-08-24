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

import json


def extract_message_field(buffer: str) -> str:
    """Extract the current value of the ``"message"`` key from a partial JSON string.

    Scans ``buffer`` for the literal ``"message"`` key, locates the colon and
    opening quote, then accumulates characters of the string value — properly
    handling JSON escape sequences (``\\"``/``\\\\``/``\\n``/``\\t``/``\\r``/
    ``\\uXXXX``, etc.).

    Stops at the unescaped closing ``"`` OR at end-of-buffer (whichever comes
    first).  Returns whatever has been accumulated so far.

    Returns ``""`` when:
    - the buffer is empty,
    - the ``"message"`` key is not yet present,
    - the key is present but the colon or opening quote has not yet arrived.
    """
    # Locate the "message" key — must be preceded by { or , (possibly with
    # whitespace), but a simple substring search is good enough: the risk of
    # a false positive on a value containing '"message"' is accepted in exchange
    # for simplicity.  The LLM follows the schema; the key appears exactly once.
    key_token = '"message"'
    key_pos = buffer.find(key_token)
    if key_pos == -1:
        return ""

    pos = key_pos + len(key_token)

    # Skip whitespace up to the colon.
    while pos < len(buffer) and buffer[pos] in " \t\r\n":
        pos += 1

    if pos >= len(buffer) or buffer[pos] != ":":
        return ""
    pos += 1  # consume ':'

    # Skip whitespace between colon and the opening quote.
    while pos < len(buffer) and buffer[pos] in " \t\r\n":
        pos += 1

    if pos >= len(buffer) or buffer[pos] != '"':
        return ""
    pos += 1  # consume opening '"'

    # Accumulate characters of the string value.
    chars: list[str] = []
    while pos < len(buffer):
        ch = buffer[pos]
        if ch == "\\":
            # Escape sequence — need at least one more character.
            if pos + 1 >= len(buffer):
                # Incomplete escape at end of buffer — stop here; we'll get
                # more tokens next time.
                break
            esc = buffer[pos + 1]
            if esc == '"':
                chars.append('"')
                pos += 2
            elif esc == "\\":
                chars.append("\\")
                pos += 2
            elif esc == "n":
                chars.append("\n")
                pos += 2
            elif esc == "r":
                chars.append("\r")
                pos += 2
            elif esc == "t":
                chars.append("\t")
                pos += 2
            elif esc == "b":
                chars.append("\b")
                pos += 2
            elif esc == "f":
                chars.append("\f")
                pos += 2
            elif esc == "/":
                chars.append("/")
                pos += 2
            elif esc == "u":
                # \uXXXX — need 4 hex digits after "u"
                if pos + 5 >= len(buffer):
                    # Incomplete unicode escape at end of buffer — stop.
                    break
                hex_str = buffer[pos + 2 : pos + 6]
                try:
                    chars.append(chr(int(hex_str, 16)))
                except ValueError:
                    # Malformed — emit as-is and advance past the sequence.
                    chars.append(f"\\u{hex_str}")
                pos += 6
            else:
                # Unknown escape — emit literally.
                chars.append(esc)
                pos += 2
        elif ch == '"':
            # Unescaped closing quote — string is complete.
            break
        else:
            chars.append(ch)
            pos += 1

    return "".join(chars)


def try_parse_full(buffer: str) -> dict | None:
    """Attempt to parse ``buffer`` as complete JSON.

    Returns the parsed ``dict`` on success, or ``None`` if ``buffer`` is not
    yet valid JSON (i.e. the stream is still in progress).

    Used at end-of-stream to obtain the full structured payload
    (``ef_tables``, ``action_message``, canonical ``message``).
    """
    try:
        result = json.loads(buffer)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, ValueError):
        return None
