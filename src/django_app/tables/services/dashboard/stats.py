from collections.abc import Iterator
from datetime import date, timedelta

from django.db.models import F, Sum
from django.db.models.functions import TruncMonth, TruncYear
from tables.models import DashboardSessionDailyStat
from tables.services.dashboard.rollup import FINAL_STATUSES

PERIOD_GROUPS = {"day": F("day"), "month": TruncMonth("day"), "year": TruncYear("day")}

TOKEN_SUMS = {
    "prompt": Sum("prompt_tokens"),
    "completion": Sum("completion_tokens"),
    "cached": Sum("cached_prompt_tokens"),
    "total": Sum("total_tokens"),
    "cost_usd": Sum("cost_usd"),
}


def period_stats(org_id: int, first: date, last: date, group: str) -> list[dict]:
    periods = {
        start: {
            "by_status": dict.fromkeys(FINAL_STATUSES, 0),
            "tokens": dict.fromkeys(TOKEN_SUMS, 0),
        }
        for start in _period_starts(first, last, group)
    }
    rows = (
        DashboardSessionDailyStat.objects.filter(org_id=org_id, day__range=(first, last))
        .annotate(period=PERIOD_GROUPS[group])
        .values("period", "status")
        .annotate(sessions=Sum("session_count"), **TOKEN_SUMS)
        .order_by()
    )
    for row in rows:
        period = periods[row["period"]]
        period["by_status"][row["status"]] += row["sessions"]
        for key in TOKEN_SUMS:
            period["tokens"][key] += row[key]
    for period in periods.values():
        period["tokens"]["cost_usd"] = str(period["tokens"]["cost_usd"])
    return [{"period": start.isoformat(), **period} for start, period in periods.items()]


def _period_starts(first: date, last: date, group: str) -> Iterator[date]:
    if group == "month":
        first = first.replace(day=1)
    if group == "year":
        first = first.replace(month=1, day=1)
    while first <= last:
        yield first
        if group == "day":
            first += timedelta(days=1)
        elif group == "month":
            first = (first + timedelta(days=32)).replace(day=1)
        else:
            first = first.replace(year=first.year + 1)
