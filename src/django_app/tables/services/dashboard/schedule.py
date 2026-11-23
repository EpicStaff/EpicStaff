from datetime import UTC, datetime, time, timedelta

from django.conf import settings


def refresh_minutes(chosen_minutes: int | None) -> int:
    if chosen_minutes is None:
        return settings.DASHBOARD_REFRESH_MINUTES
    return min(
        max(chosen_minutes, settings.DASHBOARD_REFRESH_MINUTES_MIN),
        settings.DASHBOARD_REFRESH_MINUTES_MAX,
    )


def is_build_due(
    built_at: datetime | None, now: datetime, chosen_minutes: int | None, daily_at: time | None
) -> bool:
    if built_at is None:
        return True
    if daily_at is not None:
        scheduled = datetime.combine(now.astimezone(UTC).date(), daily_at, tzinfo=UTC)
        return built_at < scheduled <= now
    return now - built_at >= timedelta(minutes=refresh_minutes(chosen_minutes))
