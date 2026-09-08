"""Regression tests for the schedule-trigger DoS hole (EST-3874).

Two independent guards are covered here: a write-time minimum-interval floor
on the validator, and a fire-time ceiling on concurrent sessions per org.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tables.exceptions import ScheduleTriggerValidationError
from tables.models.graph_models import Graph, ScheduleTriggerNode
from tables.models.session_models import Session
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.session_manager_service import SessionManagerService
from tables.validators.schedule_trigger_validator import (
    ScheduleTriggerInputParser,
    ScheduleTriggerValidator,
)


def _schedule(every, unit, end=None):
    return {
        "run_mode": "repeat",
        "timezone": "UTC",
        "start_date_time": "2026-01-01T00:00:00",
        "interval": {"every": every, "unit": unit, "weekdays": []},
        "end": end or {"type": "never", "date_time": None, "max_runs": None},
    }


def _validate(raw):
    attrs = ScheduleTriggerInputParser().parse_to_internal_value(raw, None)
    attrs["is_active"] = True
    ScheduleTriggerValidator().validate(attrs)
    return attrs


# ------------------------------------------------------- minimum interval floor


@pytest.mark.parametrize(
    "every,unit",
    [
        (1, "seconds"),
        (30, "seconds"),
        (59, "seconds"),
    ],
)
def test_sub_floor_intervals_are_rejected(every, unit):
    with pytest.raises(ScheduleTriggerValidationError) as exc:
        _validate(_schedule(every, unit))
    assert "every" in exc.value.detail


@pytest.mark.parametrize(
    "every,unit",
    [
        (60, "seconds"),
        (300, "seconds"),
        (1, "minutes"),
        (5, "minutes"),
        (10, "minutes"),
        (1, "hours"),
        (1, "days"),
        (1, "weeks"),
        (1, "months"),
    ],
)
def test_at_or_above_floor_is_accepted(every, unit):
    attrs = _validate(_schedule(every, unit))
    assert (attrs["every"], attrs["unit"]) == (every, unit)


def test_zero_and_negative_are_rejected_by_the_shape_layer():
    """The DTO's min_value=1 fires before the validator, so the detail is nested."""
    for bad in (0, -1):
        with pytest.raises(ScheduleTriggerValidationError) as exc:
            _validate(_schedule(bad, "hours"))
        assert exc.value.detail["schedule"]["interval"]["every"]


def test_rejection_message_names_the_configured_limit():
    with pytest.raises(ScheduleTriggerValidationError) as exc:
        _validate(_schedule(1, "seconds"))
    assert "60" in str(exc.value.detail["every"])


@override_settings(SCHEDULE_MIN_INTERVAL=300)
def test_floor_is_configurable():
    """A raised floor rejects intervals the default would allow."""
    assert _validate(_schedule(5, "minutes"))["every"] == 5
    with pytest.raises(ScheduleTriggerValidationError):
        _validate(_schedule(1, "minutes"))


@override_settings(SCHEDULE_MIN_INTERVAL=0)
def test_floor_can_be_disabled():
    assert _validate(_schedule(1, "seconds"))["every"] == 1


def test_once_mode_is_unaffected_by_the_floor():
    raw = {
        "run_mode": "once",
        "timezone": "UTC",
        "start_date_time": "2026-01-01T00:00:00",
    }
    attrs = ScheduleTriggerInputParser().parse_to_internal_value(raw, None)
    attrs["is_active"] = True
    ScheduleTriggerValidator().validate(attrs)
    assert attrs["run_mode"] == "once"


def test_missing_unit_is_still_reported_as_a_unit_error():
    raw = _schedule(1, "hours")
    raw["interval"]["unit"] = None
    with pytest.raises(ScheduleTriggerValidationError) as exc:
        _validate(raw)
    assert "unit" in exc.value.detail


# ------------------------------------------------------ unit->seconds conversion


@pytest.mark.parametrize(
    "unit,expected",
    [
        ("seconds", 1),
        ("minutes", 60),
        ("hours", 3600),
        ("days", 86_400),
        ("weeks", 604_800),
    ],
)
def test_interval_seconds_converts_each_unit(unit, expected):
    from src.shared.schedule.trigger_strategies import interval_seconds

    assert interval_seconds(unit=unit, every=1) == expected
    assert interval_seconds(unit=unit, every=3) == expected * 3


def test_interval_seconds_returns_none_for_unknown_unit():
    from src.shared.schedule.trigger_strategies import interval_seconds

    assert interval_seconds(unit="fortnights", every=1) is None


def test_every_unit_choice_has_a_duration():
    """Guards against a new TimeUnit silently bypassing the floor."""
    from src.shared.schedule.trigger_strategies import interval_seconds

    for unit in ScheduleTriggerNode.TimeUnit.values:
        assert interval_seconds(unit=unit, every=1) is not None, unit


# ------------------------------------------------------------------- API surface


@pytest.fixture
def sched_client(db, django_user_model):
    from tables.models.rbac_models import Organization, OrganizationUser, Role
    from tables.models.rbac_models.rbac_enums import BuiltInRole

    org = Organization.objects.create(name="Sched Org")
    user = django_user_model.objects.create_user(
        email="sched@example.com", password="StrongPass123!"
    )
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client, org


@pytest.mark.django_db
def test_api_rejects_sub_floor_interval(sched_client):
    client, org = sched_client
    graph = Graph.objects.create(name="dos-flow", org=org)
    resp = client.post(
        "/api/schedule-trigger-nodes/",
        {
            "graph": graph.id,
            "node_name": "flood",
            "is_active": True,
            "schedule": _schedule(1, "seconds"),
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "every" in str(resp.data)
    assert not ScheduleTriggerNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_api_accepts_floor_interval(sched_client):
    client, org = sched_client
    graph = Graph.objects.create(name="ok-flow", org=org)
    resp = client.post(
        "/api/schedule-trigger-nodes/",
        {
            "graph": graph.id,
            "node_name": "hourly",
            "is_active": True,
            "schedule": _schedule(1, "hours"),
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = ScheduleTriggerNode.objects.get(id=resp.data["id"])
    assert (node.every, node.unit) == (1, "hours")


@pytest.mark.django_db
def test_the_floor_lives_at_the_serializer_boundary(sched_client):
    """ScheduleTriggerService.create_node is a bare objects.create by design.

    Enforcement belongs to the serializer, whose create/update are the only
    production callers of the service. A shell/ORM caller bypasses the floor,
    which is why the service is the right tool for testing the fire-time cap
    in isolation -- but is NOT a valid way to test the floor itself.
    """
    client, org = sched_client
    graph = Graph.objects.create(name="bypass-flow", org=org)

    node = ScheduleTriggerService().create_node(
        dict(
            graph=graph,
            node_name="bypass",
            is_active=True,
            run_mode="repeat",
            timezone="UTC",
            start_date_time="2026-01-01T00:00:00Z",
            every=1,
            unit="seconds",
            weekdays=[],
            end_type="never",
        )
    )
    assert node.every == 1

    resp = client.post(
        "/api/schedule-trigger-nodes/",
        {
            "graph": graph.id,
            "node_name": "via-api",
            "is_active": True,
            "schedule": _schedule(1, "seconds"),
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "every" in str(resp.data)


# ----------------------------------------------------------- concurrency ceiling


@pytest.fixture
def sched_node(db):
    from tables.models.rbac_models import Organization

    org = Organization.objects.create(name="Cap Org")
    graph = Graph.objects.create(name="capped-flow", org=org)
    node = ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="capped",
        is_active=True,
        run_mode="repeat",
        timezone="UTC",
        start_date_time="2026-01-01T00:00:00Z",
        every=1,
        unit="hours",
        weekdays=[],
        end_type="never",
    )
    return node, graph, org


def _make_sessions(graph, status, count):
    for _ in range(count):
        Session.objects.create(graph=graph, status=status, variables={})


@pytest.mark.django_db
@override_settings(SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG=2)
def test_fire_is_skipped_when_org_is_at_the_cap(sched_node, mocker):
    node, graph, _ = sched_node
    _make_sessions(graph=graph, status=Session.SessionStatus.RUN, count=2)
    start = mocker.patch.object(ScheduleTriggerService, "_start_session")

    ScheduleTriggerService().handle_schedule_trigger(node.id)

    start.assert_not_called()
    node.refresh_from_db()
    assert node.current_runs == 0
    assert node.is_active is True


@pytest.mark.django_db
@override_settings(SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG=2)
def test_fire_proceeds_below_the_cap(sched_node, mocker):
    node, graph, _ = sched_node
    _make_sessions(graph=graph, status=Session.SessionStatus.RUN, count=1)
    start = mocker.patch.object(ScheduleTriggerService, "_start_session")

    ScheduleTriggerService().handle_schedule_trigger(node.id)

    start.assert_called_once()
    node.refresh_from_db()
    assert node.current_runs == 1


@pytest.mark.django_db
@override_settings(SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG=1)
def test_wait_for_user_sessions_do_not_block_the_schedule(sched_node, mocker):
    """A session parked on human input must not wedge a schedule forever."""
    node, graph, _ = sched_node
    _make_sessions(graph=graph, status=Session.SessionStatus.WAIT_FOR_USER, count=5)
    start = mocker.patch.object(ScheduleTriggerService, "_start_session")

    ScheduleTriggerService().handle_schedule_trigger(node.id)

    start.assert_called_once()


@pytest.mark.django_db
@override_settings(SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG=1)
def test_finished_sessions_do_not_count_towards_the_cap(sched_node, mocker):
    node, graph, _ = sched_node
    for status in (
        Session.SessionStatus.END,
        Session.SessionStatus.ERROR,
        Session.SessionStatus.STOP,
        Session.SessionStatus.EXPIRED,
    ):
        _make_sessions(graph=graph, status=status, count=2)
    start = mocker.patch.object(ScheduleTriggerService, "_start_session")

    ScheduleTriggerService().handle_schedule_trigger(node.id)

    start.assert_called_once()


@pytest.mark.django_db
def test_count_live_sessions_is_scoped_to_one_org(sched_node):
    from tables.models.rbac_models import Organization

    _, graph, org = sched_node
    other_org = Organization.objects.create(name="Other Org")
    other_graph = Graph.objects.create(name="other-flow", org=other_org)
    _make_sessions(graph=graph, status=Session.SessionStatus.RUN, count=3)
    _make_sessions(graph=other_graph, status=Session.SessionStatus.PENDING, count=7)

    service = SessionManagerService()
    assert service.count_live_sessions(org_id=org.id) == 3
    assert service.count_live_sessions(org_id=other_org.id) == 7
