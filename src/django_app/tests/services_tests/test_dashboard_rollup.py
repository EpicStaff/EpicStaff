from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from rbac.models import Organization
from tables.models import DURATION_BUCKET_COUNT, DashboardSessionDailyStat, Graph, Session
from tables.models.session_models import SessionPrincipal, SessionTrigger
from tables.services.dashboard.rollup import (
    earliest_finished_day,
    roll_up_days,
    roll_up_since_last_build,
)

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 19)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Globex")


@pytest.fixture
def flow(org):
    return Graph.objects.create(name="Orders", org=org)


def _at(day, hour=12, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _session(
    flow,
    status=Session.SessionStatus.END,
    finished_at=None,
    duration=timedelta(seconds=10),
    parent=None,
    token_usage=None,
):
    finished_at = finished_at or _at(DAY)
    return Session.objects.create(
        graph=flow,
        status=status,
        status_updated_at=finished_at,
        created_at=finished_at - duration,
        finished_at=finished_at,
        parent_session=parent,
        token_usage=token_usage or {},
    )


def _stats(org):
    return list(DashboardSessionDailyStat.objects.filter(org=org))


def test_session_counts_on_the_day_it_finished(org, flow):
    next_day = DAY + timedelta(days=1)
    _session(flow, finished_at=_at(next_day, hour=0, minute=10), duration=timedelta(minutes=20))

    roll_up_days(org.id, DAY, next_day)

    [stat] = _stats(org)
    assert stat.day == next_day
    assert stat.session_count == 1


def test_subflow_and_running_sessions_are_skipped(org, flow):
    root = _session(flow)
    _session(flow, parent=root)
    Session.objects.create(
        graph=flow,
        status=Session.SessionStatus.RUN,
        status_updated_at=_at(DAY),
        created_at=_at(DAY),
    )

    roll_up_days(org.id, DAY, DAY)

    assert [stat.session_count for stat in _stats(org)] == [1]


def test_sessions_of_binned_flow_still_count(org, flow):
    _session(flow)
    flow.delete()

    roll_up_days(org.id, DAY, DAY)

    assert [stat.graph_id for stat in _stats(org)] == [flow.id]


def test_sessions_are_grouped_by_status_trigger_source_and_test_flag(org, flow):
    _session(flow)
    test_run = _session(flow)
    SessionTrigger.objects.create(
        session=test_run,
        trigger_type=SessionTrigger.TriggerType.WEBHOOK,
        extra={SessionTrigger.TEST_RUN_EXTRA_KEY: True},
    )
    plugin_run = _session(flow, status=Session.SessionStatus.ERROR)
    SessionPrincipal.objects.create(
        session=plugin_run,
        kind=SessionPrincipal.ActionKind.PLUGIN,
        plugin_identifier="slack",
    )

    roll_up_days(org.id, DAY, DAY)

    assert {
        (s.status, s.trigger_type, s.source_kind, s.source_ref, s.source_name, s.is_test)
        for s in _stats(org)
    } == {
        ("end", "unknown", "unknown", "", "", False),
        ("end", "webhook", "unknown", "", "", True),
        ("error", "unknown", "plugin", "slack", "slack", False),
    }


def test_durations_fill_histogram_buckets(org, flow):
    for duration in (timedelta(seconds=0.4), timedelta(seconds=70), timedelta(days=2)):
        _session(flow, duration=duration)

    roll_up_days(org.id, DAY, DAY)

    [stat] = _stats(org)
    expected = [0] * DURATION_BUCKET_COUNT
    expected[0] = expected[5] = expected[14] = 1
    assert stat.duration_histogram == expected
    assert stat.duration_seconds_sum == 172870


def test_tokens_are_summed_and_tokens_without_price_count_as_unknown_cost(org, flow):
    _session(flow, token_usage={})
    _session(
        flow,
        token_usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cached_prompt_tokens": 5,
            "total_tokens": 120,
            "successful_requests": 2,
            "total_cost_usd": 0.00026625,
        },
    )
    _session(
        flow,
        token_usage={
            "prompt_tokens": 10,
            "completion_tokens": 0,
            "cached_prompt_tokens": 0,
            "total_tokens": 10,
            "successful_requests": 1,
        },
    )

    roll_up_days(org.id, DAY, DAY)

    [stat] = _stats(org)
    assert (
        stat.prompt_tokens,
        stat.completion_tokens,
        stat.cached_prompt_tokens,
        stat.total_tokens,
        stat.successful_requests,
    ) == (110, 20, 5, 130, 3)
    assert stat.cost_usd == Decimal("0.000266")
    assert stat.unknown_cost_count == 1


def test_rerun_replaces_only_the_given_days(org, flow):
    three_days_ago = DAY - timedelta(days=3)
    old = _session(flow, finished_at=_at(three_days_ago))
    _session(flow, finished_at=_at(DAY))
    roll_up_days(org.id, three_days_ago, DAY)

    old.delete()
    _session(flow, finished_at=_at(DAY))
    roll_up_days(org.id, DAY - timedelta(days=1), DAY)

    assert {stat.day: stat.session_count for stat in _stats(org)} == {
        three_days_ago: 1,
        DAY: 2,
    }


def test_sessions_of_other_organizations_are_ignored(org, other_org):
    _session(Graph.objects.create(name="Foreign", org=other_org))

    roll_up_days(org.id, DAY, DAY)

    assert not DashboardSessionDailyStat.objects.exists()


def test_earliest_finished_day(org, flow):
    assert earliest_finished_day(org.id) is None

    _session(flow, finished_at=_at(DAY))
    _session(flow, finished_at=_at(DAY - timedelta(days=5), hour=23, minute=59))

    assert earliest_finished_day(org.id) == DAY - timedelta(days=5)


def test_first_run_counts_every_day_from_the_oldest_session(org, flow):
    oldest_day = DAY - timedelta(days=10)
    _session(flow, finished_at=_at(oldest_day))
    _session(flow, finished_at=_at(DAY))

    roll_up_since_last_build(org.id, rolled_up_through=None, today=DAY)

    assert {stat.day for stat in _stats(org)} == {oldest_day, DAY}


def test_next_run_recounts_only_yesterday_and_today(org, flow):
    old_day = DAY - timedelta(days=3)
    yesterday = DAY - timedelta(days=1)
    old = _session(flow, finished_at=_at(old_day))
    roll_up_since_last_build(org.id, rolled_up_through=None, today=DAY)

    old.delete()
    _session(flow, finished_at=_at(yesterday))
    roll_up_since_last_build(org.id, rolled_up_through=DAY, today=DAY)

    assert {stat.day: stat.session_count for stat in _stats(org)} == {
        old_day: 1,
        yesterday: 1,
    }


def test_run_after_a_pause_recounts_from_the_last_counted_day(org, flow):
    missed_day = DAY - timedelta(days=4)
    _session(flow, finished_at=_at(missed_day))

    roll_up_since_last_build(org.id, rolled_up_through=DAY - timedelta(days=5), today=DAY)

    assert {stat.day for stat in _stats(org)} == {missed_day}
