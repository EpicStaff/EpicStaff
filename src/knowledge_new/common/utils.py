from datetime import UTC, datetime

__all__ = [
    "utcnow",
]

from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_key(*values: Any) -> str:
    """Join `values` into a colon-delimited key, in order."""
    return ':'.join(str(v) for v in values)