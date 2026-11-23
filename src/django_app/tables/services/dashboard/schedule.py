from datetime import UTC, datetime, time, timedelta

from django.conf import settings


def refresh_minutes(chosen_minutes: int | None) -> int:
    if chosen_minutes is None:
        return settings.DASHBOARD_REFRESH_MINUTES
    return min(
        max(chosen_minutes, settings.DASHBOARD_REFRESH_MINUTES_MIN),
        settings.DASHBOARD_REFRESH_MINUTES_MAX,
    )


def next_build_at(
    built_at: datetime, chosen_minutes: int | None, daily_at: time | None
) -> datetime:
    if daily_at is not None:
        scheduled = datetime.combine(built_at.astimezone(UTC).date(), daily_at, tzinfo=UTC)
        return scheduled if scheduled > built_at else scheduled + timedelta(days=1)
    return built_at + timedelta(minutes=refresh_minutes(chosen_minutes))


def is_build_due(
    built_at: datetime | None, now: datetime, chosen_minutes: int | None, daily_at: time | None
) -> bool:
    return built_at is None or now >= next_build_at(built_at, chosen_minutes, daily_at)
