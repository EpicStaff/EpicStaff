from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, tzinfo

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.shared.models import ScheduleTriggerNodePayload


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz

        return dt.replace(tzinfo=_tz.utc)
    return dt


@dataclass(frozen=True)
class ScheduleTriggerContext:
    node: ScheduleTriggerNodePayload
    node_tz: tzinfo
    start_dt: datetime | None
    end_dt: datetime | None
    every: int
    weekdays: list[str]


@dataclass(frozen=True)
class StartClock:
    minute: int
    hour: int
    day: int
    weekday: int


class ScheduleTriggerStrategy(ABC):
    _WEEKDAY_SHORT = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

    @staticmethod
    def _extract_start_clock(ctx: ScheduleTriggerContext) -> StartClock:
        """Cron-style fields of start_date_time in ctx.node_tz; falls back to (0, 0, 1, 0)."""
        dt = _ensure_aware(ctx.node.start_date_time)
        if dt is None:
            return StartClock(minute=0, hour=0, day=1, weekday=0)
        local = dt.astimezone(ctx.node_tz)
        return StartClock(
            minute=local.minute,
            hour=local.hour,
            day=local.day,
            weekday=local.weekday(),
        )

    @staticmethod
    def _build_cron_trigger(ctx: ScheduleTriggerContext, crontab: str) -> CronTrigger:
        """5-field crontab + ctx start_date / end_date / tz. second='0' matches once-per-minute semantics."""
        minute, hour, day, month, day_of_week = crontab.split()
        return CronTrigger(
            second="0",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )

    @abstractmethod
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger | None: ...


class OnceTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger | None:
        if ctx.start_dt is None:
            return None
        return DateTrigger(run_date=ctx.start_dt, timezone=ctx.node_tz)


class SecondsTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        return IntervalTrigger(
            seconds=ctx.every,
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )


class MinutesTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        return IntervalTrigger(
            minutes=ctx.every,
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )


class HoursTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        return IntervalTrigger(
            hours=ctx.every,
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )


class DaysTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        clock = self._extract_start_clock(ctx)
        if ctx.weekdays:
            return self._build_cron_trigger(
                ctx, f"{clock.minute} {clock.hour} * * {','.join(ctx.weekdays)}"
            )
        if ctx.every == 1:
            return self._build_cron_trigger(ctx, f"{clock.minute} {clock.hour} * * *")
        return IntervalTrigger(
            days=ctx.every,
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )


class WeeksTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        clock = self._extract_start_clock(ctx)
        wd = (
            ",".join(ctx.weekdays)
            if ctx.weekdays
            else self._WEEKDAY_SHORT[clock.weekday]
        )
        if ctx.every == 1:
            return self._build_cron_trigger(
                ctx, f"{clock.minute} {clock.hour} * * {wd}"
            )
        return CronTrigger(
            second="0",
            minute=clock.minute,
            hour=clock.hour,
            day_of_week=wd,
            week=f"*/{ctx.every}",
            timezone=ctx.node_tz,
            start_date=ctx.start_dt,
            end_date=ctx.end_dt,
        )


class MonthsTriggerStrategy(ScheduleTriggerStrategy):
    def build(self, ctx: ScheduleTriggerContext) -> BaseTrigger:
        clock = self._extract_start_clock(ctx)
        return self._build_cron_trigger(
            ctx, f"{clock.minute} {clock.hour} {clock.day} */{ctx.every} *"
        )


ONCE_STRATEGY: ScheduleTriggerStrategy = OnceTriggerStrategy()

UNIT_STRATEGIES: dict[str, ScheduleTriggerStrategy] = {
    "seconds": SecondsTriggerStrategy(),
    "minutes": MinutesTriggerStrategy(),
    "hours": HoursTriggerStrategy(),
    "days": DaysTriggerStrategy(),
    "weeks": WeeksTriggerStrategy(),
    "months": MonthsTriggerStrategy(),
}
