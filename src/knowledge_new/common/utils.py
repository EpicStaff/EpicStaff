from datetime import UTC, datetime
from typing import Any

__all__ = [
    "utcnow",
    "make_key",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_key(*values: Any) -> str:
    """Join `values` into a colon-delimited key, in order."""
    return ":".join(str(v) for v in values)
