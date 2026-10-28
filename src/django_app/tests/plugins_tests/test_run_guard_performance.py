"""What the run guard costs: the walk is done once per run, owned files are matched by binary
search, and the organizations it could refuse runs in are one query."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plugins.exceptions import PluginSuspendedError
from plugins.models import GrantState
from plugins.ownership.ownership_recorder import ownable_models
from plugins.runs import run_guard
from plugins.runs.owned_resource_index import BlockingOwner, OwnedResourceIndex
from plugins.runs.run_guard import (
    PluginRunGuard,
    _may_refuse_in,
    organizations_with_refusable_runs,
)
from rbac.models import Organization
from tables.models import Session
from tables.services.run_admission import RunKind, RunSubject
from tables.services.run_resources import RunResourceCollector, RunResources
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.suspension_helpers import flow, orphan, own, set_state
from tests.services_tests.session_trigger_creation_test import _empty_session_data
from tests.services_tests.test_run_session_query_count import (  # noqa: F401
    RUN_SESSION_QUERY_COUNT,
    _run,
    org,
    published,
    representative_graph,
    secret,
    subgraph,
)

pytestmark = [pytest.mark.django_db]

# run_session's budget when the organization has a suspended grant owning something the
# flow does not use: the guard walks the flow once, and matches what it uses against the
# owned rows before anything is written and again just before the publish. If a change
# raises it, find the new query.
RUN_SESSION_QUERY_COUNT_WHILE_A_GRANT_IS_SUSPENDED = 78


@pytest.fixture
def weather(running_plugin):
    return running_plugin()


@pytest.fixture
def almanac(running_plugin):
    return running_plugin(id="almanac", name="Almanac")


@pytest.fixture
def walks(monkeypatch):
    """Count the guard's walks."""
    subjects = []

    class CountingCollector(RunResourceCollector):
        def collect(self, subject):
            subjects.append(subject)
            return super().collect(subject)

    monkeypatch.setattr(run_guard, "RunResourceCollector", CountingCollector)
    return subjects


def _subject(graph) -> RunSubject:
    return RunSubject(RunKind.FLOW, graph.pk, graph.org_id)


def _suspended_almanac_owning_an_unrelated_flow(almanac, grant_to, organization):
    """Leaves the guard's fast path: a run of the organization is walked."""
    grant = set_state(grant_to(almanac, organization), GrantState.SUSPENDED)
    own(flow(organization, "Almanac"), grant)
    return grant


# ---- the walk is reused ----


def test_run_session_stays_within_its_budget_while_a_grant_of_the_org_is_suspended(
    representative_graph, org, almanac, grant_to, published, walks, django_assert_num_queries
):
    _suspended_almanac_owning_an_unrelated_flow(almanac, grant_to, org)
    # A running server has looked these up long ago; whether this process has depends on
    # which tests ran before.
    ContentType.objects.get_for_models(*ownable_models())

    with django_assert_num_queries(RUN_SESSION_QUERY_COUNT_WHILE_A_GRANT_IS_SUSPENDED):
        _run(representative_graph)

    assert len(published) == 1
    assert walks == [_subject(representative_graph)]


def test_without_a_refusable_grant_the_budget_is_the_plain_one(
    representative_graph, published, walks, django_assert_num_queries
):
    with django_assert_num_queries(RUN_SESSION_QUERY_COUNT):
        _run(representative_graph)

    assert walks == []


def test_the_recheck_matches_the_first_walk_again_without_walking(
    weather, almanac, grant_to, acme, walks
):
    weather_grant = grant_to(weather, acme)
    forecast = flow(acme, "Weather forecast")
    own(forecast, weather_grant)
    _suspended_almanac_owning_an_unrelated_flow(almanac, grant_to, acme)
    guard = PluginRunGuard()
    first_look = guard.check(_subject(forecast))
    set_state(weather_grant, GrantState.SUSPENDED)

    with CaptureQueriesContext(connection) as captured, pytest.raises(PluginSuspendedError):
        guard.recheck(_subject(forecast), first_look)

    assert walks == [_subject(forecast)]
    assert 1 <= len(captured.captured_queries) <= 2


def test_a_run_not_walked_the_first_time_is_checked_from_the_start_again(
    weather, grant_to, acme, walks
):
    weather_grant = grant_to(weather, acme)
    forecast = flow(acme, "Weather forecast")
    own(forecast, weather_grant)
    guard = PluginRunGuard()
    first_look = guard.check(_subject(forecast))
    set_state(weather_grant, GrantState.SUSPENDED)

    with pytest.raises(PluginSuspendedError):
        guard.recheck(_subject(forecast), first_look)

    assert first_look is None
    assert walks == [_subject(forecast)]


def test_a_suspension_committed_while_a_run_is_built_refuses_it_before_the_publish(
    weather, almanac, grant_to, acme, client_as, admin_acme, redis_client_mock, monkeypatch
):
    weather_grant = grant_to(weather, acme)
    forecast = flow(acme, "Weather forecast")
    own(forecast, weather_grant)
    _suspended_almanac_owning_an_unrelated_flow(almanac, grant_to, acme)

    def suspend_while_building(session, **kwargs):
        set_state(weather_grant, GrantState.SUSPENDED)
        return _empty_session_data()

    monkeypatch.setattr(SessionManagerService(), "create_session_data", suspend_while_building)
    redis_client_mock.reset_mock()
    olga = client_as(admin_acme)
    olga.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = olga.post(
        reverse("run-session"), {"graph_id": forecast.pk, "variables": {}}, format="json"
    )

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "plugin_suspended"
    redis_client_mock.publish.assert_not_called()
    assert list(Session.objects.filter(graph=forecast).values_list("status", flat=True)) == [
        Session.SessionStatus.STOP
    ]


# ---- owned files under a folder ----


def _owner(identifier: str, grant_id: int = 1) -> BlockingOwner:
    return BlockingOwner(
        plugin_identifier=identifier,
        plugin_name=identifier,
        grant_id=grant_id,
        grant_state="suspended",
        since=None,
    )


def _uses(*prefixes: str) -> RunResources:
    return RunResources(refs=frozenset(), storage_prefixes=frozenset(prefixes))


def test_with_several_owners_under_a_folder_the_lowest_identifier_names_it():
    weather_owner, alerts_owner, zebra_owner = _owner("weather"), _owner("alerts", 2), _owner("zebra", 3)
    index = OwnedResourceIndex(
        {},
        [
            *((f"big/{number:05d}.txt", weather_owner) for number in range(5000)),
            ("big/zz.txt", zebra_owner),
            ("big/sub/a.txt", alerts_owner),
        ],
    )

    assert index.first_owner(_uses("big/")) == alerts_owner
    assert index.first_owner(_uses("big/0")) == weather_owner
    assert index.first_owner(_uses("big/zz")) == zebra_owner


def test_a_sibling_folder_with_a_longer_name_is_not_under_the_prefix():
    weather_owner = _owner("weather")
    index = OwnedResourceIndex({}, [("bigger/a.txt", weather_owner), ("bi.txt", weather_owner)])

    assert index.first_owner(_uses("big/")) is None
    assert index.first_owner(_uses("bigger/")) == weather_owner


def test_a_folder_with_nothing_owned_under_it_names_no_one():
    index = OwnedResourceIndex({}, [("a/1.txt", _owner("weather"))])

    assert index.first_owner(_uses("b/")) is None
    assert not index.is_empty
    assert OwnedResourceIndex({}, []).is_empty


# ---- the organizations whose runs could be refused ----


def test_the_organizations_with_refusable_runs_are_exactly_those_the_guard_checks(
    weather, grant_to
):
    shapes = {name: Organization.objects.create(name=f"Shape {name}") for name in (
        "no grant",
        "active grant owning rows",
        "suspended grant owning nothing",
        "suspended grant owning a row",
        "granting grant owning a row",
        "install failed grant owning a row",
        "row whose grant is gone",
    )}
    own(flow(shapes["active grant owning rows"], "Active"), grant_to(weather, shapes["active grant owning rows"]))
    grant_to(weather, shapes["suspended grant owning nothing"], state=GrantState.SUSPENDED)
    for name, state in (
        ("suspended grant owning a row", GrantState.SUSPENDED),
        ("granting grant owning a row", GrantState.GRANTING),
        ("install failed grant owning a row", GrantState.INSTALL_FAILED),
    ):
        own(flow(shapes[name], name), grant_to(weather, shapes[name], state=state))
    orphan(flow(shapes["row whose grant is gone"], "Old"), shapes["row whose grant is gone"])

    with CaptureQueriesContext(connection) as captured:
        refusable = set(organizations_with_refusable_runs())

    assert refusable == {
        shapes[name].pk
        for name in (
            "suspended grant owning a row",
            "granting grant owning a row",
            "install failed grant owning a row",
            "row whose grant is gone",
        )
    }
    assert refusable == {
        organization.pk for organization in shapes.values() if _may_refuse_in(organization.pk)
    }
    assert len(captured.captured_queries) == 1
