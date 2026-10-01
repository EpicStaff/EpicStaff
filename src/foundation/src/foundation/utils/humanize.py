"""Parse human-friendly byte sizes and durations into numbers."""

import re
from datetime import timedelta

__all__ = [
    "to_byte_size",
    "to_time",
]

_VALUE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z]+)$")
_DATA_UNITS_MAP = {
    "b": 1,
    "kb": 2**10,
    "mb": 2**20,
    "gb": 2**30,
}


def to_byte_size(value: str) -> int:
    """Parse a byte-size string into a number of bytes.

    Accepts a plain integer (``"1024"``) or a number with a unit
    ``b``/``kb``/``mb``/``gb`` (powers of 1024), e.g. ``"10mb"``.

    Raises:
        ValueError: The string is neither a plain integer nor ``<number><unit>``,
            or the unit is unknown.
    """
    value = value.strip().lower()
    try:
        return int(value)
    except ValueError:
        pass

    match = _VALUE_PATTERN.match(value)
    if match is None:
        raise ValueError(f"Unexpected value format: {value!r}")

    number, unit = match.groups()
    if unit not in _DATA_UNITS_MAP:
        raise ValueError(f"Unexpected unit: {unit!r} in {value!r}")
    return int(float(number) * _DATA_UNITS_MAP[unit])


_TIME_UNITS_MAP = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def to_time(value: str) -> float:
    """Parse a duration string into seconds.

    Accepts a plain number (``"30"``) or a number with a unit
    ``s``/``m``/``h``/``d``, e.g. ``"5m"``.

    Raises:
        ValueError: The string is neither a plain number nor ``<number><unit>``,
            or the unit is unknown.
    """
    value = value.strip().lower()
    try:
        return float(value)
    except ValueError:
        pass

    match = _VALUE_PATTERN.match(value)
    if match is None:
        raise ValueError(f"Unexpected value format: {value!r}")

    number, unit = match.groups()
    if unit not in _TIME_UNITS_MAP:
        raise ValueError(f"Unexpected unit: {unit!r} in {value!r}")
    return timedelta(**{_TIME_UNITS_MAP[unit]: float(number)}).total_seconds()
