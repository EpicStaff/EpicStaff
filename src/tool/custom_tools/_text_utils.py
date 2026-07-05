"""Shared text-decoding helpers for file-based custom tools."""

from typing import Tuple


def decode_bytes(raw: bytes) -> Tuple[str | None, str | None]:
    """Decode raw bytes to text, trying utf-8 first and falling back to
    charset-normalizer based detection.

    Returns a (text, encoding) tuple. Both are None if the bytes could not
    be decoded as text at all (e.g. a binary file).
    """
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        match = from_bytes(raw).best()
        if match is None:
            return None, None
        return str(match), match.encoding
    except Exception:
        return None, None
