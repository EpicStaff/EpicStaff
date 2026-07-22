from datetime import datetime, timezone


def ensure_aware(dt: datetime | None) -> datetime | None:
    """Ensure datetime is tz-aware: attach UTC if tzinfo is missing, otherwise return as-is."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
