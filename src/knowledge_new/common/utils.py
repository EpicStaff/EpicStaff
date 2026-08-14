from datetime import UTC, datetime

__all__ = [
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(UTC)
