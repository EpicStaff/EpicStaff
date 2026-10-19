import re
from typing import NamedTuple

__all__ = ["Rate", "to_rate"]

# Durations use the shared src.shared.humanize.to_time; rates are chat's own.
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_RATE_PATTERN = re.compile(r"^(\d+)\s*/\s*([a-z]+)$")


class Rate(NamedTuple):
    """At most `limit` hits per fixed window of `window_seconds`."""

    limit: int
    window_seconds: int


def to_rate(value: str) -> Rate:
    """Read a rate `<count>/<unit>` (`30/m`, `20/h`); the count is a whole number >= 1, the unit s, m, h or d."""
    match = _RATE_PATTERN.match(value.strip().lower())
    if match is None:
        raise ValueError(f"Unexpected rate format: {value!r} (use <count>/<unit>, e.g. 30/m)")
    count, unit = match.groups()
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"Unexpected rate unit {unit!r} in {value!r} (use s, m, h or d)")
    if int(count) < 1:
        # 0 would refuse every client; turning a limit off is not what a rate is for.
        raise ValueError(f"Rate count must be at least 1: {value!r}")
    return Rate(int(count), _UNIT_SECONDS[unit])
