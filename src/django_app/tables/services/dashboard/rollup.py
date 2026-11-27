from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    DecimalField,
    DurationField,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Min,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Extract, Greatest, TruncDate
from tables.models import (
    DURATION_BUCKET_COUNT,
    DURATION_BUCKET_UPPER_SECONDS,
    DashboardSessionDailyStat,
    Session,
)
from tables.models.session_models import SessionPrincipal

UNKNOWN = "unknown"

FINAL_STATUSES = (
    Session.SessionStatus.END,
    Session.SessionStatus.ERROR,
    Session.SessionStatus.STOP,
    Session.SessionStatus.EXPIRED,
)

TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "cached_prompt_tokens",
    "total_tokens",
    "successful_requests",
)

API_KEY_KINDS = (
    SessionPrincipal.ActionKind.API_KEY_USER,
    SessionPrincipal.ActionKind.API_KEY_SYSTEM,
)

JSON_NUMBER = DecimalField(max_digits=30, decimal_places=12)
COST_STEP = Decimal("0.000001")


def earliest_finished_day(org_id: int) -> date | None:
    first = _finished_root_sessions(org_id).aggregate(first=Min("finished_at"))["first"]
    return first.astimezone(UTC).date() if first else None


def roll_up_since_last_build(org_id: int, rolled_up_through: date | None, today: date) -> None:
    if rolled_up_through is None:
        day = earliest_finished_day(org_id) or today
    else:
        day = min(rolled_up_through, today - timedelta(days=1))
    while day <= today:
        roll_up_days(org_id, day, day)
        day += timedelta(days=1)


def roll_up_days(org_id: int, first_day: date, last_day: date) -> None:
    start = datetime.combine(first_day, time.min, tzinfo=UTC)
    end = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=UTC)
    dimensions = _dimensions()
    rows = (
        _finished_root_sessions(org_id)
        .filter(finished_at__gte=start, finished_at__lt=end)
        .alias(duration_seconds=_duration_seconds())
        .annotate(**dimensions)
        .values("graph_id", "status", *dimensions)
        .annotate(**_totals())
        .order_by()
    )
    stats = [_to_stat(org_id, row) for row in rows]

    with transaction.atomic():
        DashboardSessionDailyStat.objects.filter(
            org_id=org_id, day__range=(first_day, last_day)
        ).delete()
        DashboardSessionDailyStat.objects.bulk_create(stats)


def _finished_root_sessions(org_id: int) -> QuerySet:
    return Session.objects.filter(
        graph__org_id=org_id,
        parent_session__isnull=True,
        status__in=FINAL_STATUSES,
        finished_at__isnull=False,
    )


def _duration_seconds() -> Greatest:
    duration = ExpressionWrapper(F("finished_at") - F("created_at"), output_field=DurationField())
    return Greatest(Extract(duration, "epoch", output_field=FloatField()), Value(0.0))


def _dimensions() -> dict:
    source_ref = Case(
        When(
            principal__kind=SessionPrincipal.ActionKind.USER,
            then=Cast("principal__user_id", CharField()),
        ),
        When(
            principal__kind__in=API_KEY_KINDS,
            then=Cast("principal__api_key_id", CharField()),
        ),
        When(
            principal__kind=SessionPrincipal.ActionKind.PLUGIN,
            then=F("principal__plugin_identifier"),
        ),
        output_field=CharField(),
    )
    return {
        "day": TruncDate("finished_at", tzinfo=UTC),
        "trigger_type": Coalesce("trigger__trigger_type", Value(UNKNOWN)),
        "source_kind": Coalesce("principal__kind", Value(UNKNOWN)),
        "source_ref": Coalesce(source_ref, Value("")),
        "is_test": Case(
            When(trigger__extra__test_run=True, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
    }


def _totals() -> dict:
    source_name = Case(
        When(principal__kind=SessionPrincipal.ActionKind.USER, then=F("principal__email")),
        When(principal__kind__in=API_KEY_KINDS, then=F("principal__api_key__name")),
        When(
            principal__kind=SessionPrincipal.ActionKind.PLUGIN,
            then=F("principal__plugin_identifier"),
        ),
        output_field=CharField(),
    )
    unknown_cost = Q(token_usage__total_tokens__gt=0) & (
        Q(token_usage__total_cost_usd__isnull=True) | Q(token_usage__total_cost_usd=None)
    )
    return {
        "graph_name": Max("graph__name"),
        "source_name": Max(source_name),
        "session_count": Count("pk"),
        "duration_seconds_sum": Sum("duration_seconds"),
        **{
            f"bucket_{index}": Count("pk", filter=_bucket(index))
            for index in range(DURATION_BUCKET_COUNT)
        },
        **{field: Sum(_json_number(field)) for field in TOKEN_FIELDS},
        "cost_usd": Sum(_json_number("total_cost_usd")),
        "unknown_cost_count": Count("pk", filter=unknown_cost),
    }


def _bucket(index: int) -> Q:
    condition = Q()
    if index > 0:
        condition &= Q(duration_seconds__gt=DURATION_BUCKET_UPPER_SECONDS[index - 1])
    if index < len(DURATION_BUCKET_UPPER_SECONDS):
        condition &= Q(duration_seconds__lte=DURATION_BUCKET_UPPER_SECONDS[index])
    return condition


def _json_number(key: str) -> Cast:
    return Cast(KeyTextTransform(key, "token_usage"), JSON_NUMBER)


def _to_stat(org_id: int, row: dict) -> DashboardSessionDailyStat:
    return DashboardSessionDailyStat(
        org_id=org_id,
        day=row["day"],
        graph_id=row["graph_id"],
        graph_name=row["graph_name"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        source_kind=row["source_kind"],
        source_ref=row["source_ref"],
        source_name=row["source_name"] or "",
        is_test=row["is_test"],
        session_count=row["session_count"],
        duration_seconds_sum=round(row["duration_seconds_sum"] or 0),
        duration_histogram=[row[f"bucket_{index}"] for index in range(DURATION_BUCKET_COUNT)],
        **{field: int(row[field] or 0) for field in TOKEN_FIELDS},
        cost_usd=(row["cost_usd"] or Decimal(0)).quantize(COST_STEP),
        unknown_cost_count=row["unknown_cost_count"],
    )
