from datetime import timedelta
import re

__all__ = [
    "to_byte_size",
    "to_time",
]

_VALUE_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)\s*([a-z]+)$')
_DATA_UNITS_MAP = {
    "b": 1,
    "kb": 2 ** 10,
    "mb": 2 ** 20,
    "gb": 2 ** 30,
}


def to_byte_size(value: str) -> int:
    value = value.strip().lower()
    try:
        return int(value)
    except ValueError:
        pass

    match = _VALUE_PATTERN.match(value)
    if match is None:
        raise ValueError(f'Unexpected value format: {value!r}')

    number, unit = match.groups()
    if unit not in _DATA_UNITS_MAP:
        raise ValueError(f'Unexpected unit: {unit!r} in {value!r}')
    return int(float(number) * _DATA_UNITS_MAP[unit])


_TIME_UNITS_MAP = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def to_time(value: str) -> float:
    value = value.strip().lower()
    try:
        return float(value)
    except ValueError:
        pass

    match = _VALUE_PATTERN.match(value)
    if match is None:
        raise ValueError(f'Unexpected value format: {value!r}')

    number, unit = match.groups()
    if unit not in _TIME_UNITS_MAP:
        raise ValueError(f'Unexpected unit: {unit!r} in {value!r}')
    return timedelta(**{_TIME_UNITS_MAP[unit]: float(number)}).total_seconds()
