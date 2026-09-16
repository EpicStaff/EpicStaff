"""Shared APScheduler trigger builder for ScheduleTriggerNode.

Used by:
  - manager.services.schedule_service - to register APScheduler jobs.
  - django_app.tables.services.schedule_trigger_service - to compute next_run_date_time.

Both sides build the same trigger from the same config, so the time Django
records as "next_run" matches the time Manager will actually fire.
"""

from datetime import datetime, timezone as _tz, tzinfo

from apscheduler.triggers.base import BaseTrigger

from ..models import ScheduleTriggerNodePayload
from .trigger_strategies import (
    ONCE_STRATEGY,
    UNIT_STRATEGIES,
    ScheduleTriggerContext,
)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)


def build_trigger(
    node: ScheduleTriggerNodePayload,
    node_tz: tzinfo,
) -> BaseTrigger | None:
    """Resolve an APScheduler trigger via the Strategy registry.

    Returns None on missing/invalid config (no run_mode, missing every/unit
    for repeat, unknown unit). Caller decides what to do with None.
    """
    end_dt = _ensure_aware(node.end_date_time) if node.end_type == "on_date" else None
    start_dt = _ensure_aware(node.start_date_time)

    ctx = ScheduleTriggerContext(
        node=node,
        node_tz=node_tz,
        start_dt=start_dt,
        end_dt=end_dt,
        every=node.every or 0,
        weekdays=node.weekdays or [],
    )

    if node.run_mode == "once":
        return ONCE_STRATEGY.build(ctx)

    if not node.every or not node.unit:
        return None

    strategy = UNIT_STRATEGIES.get(node.unit)
    if strategy is None:
        return None

    return strategy.build(ctx)
