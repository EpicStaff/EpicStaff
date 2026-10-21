"""The plugin run guard: a run that uses anything a non-active grant owns is refused before it starts."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plugins.exceptions import PluginSuspendedError
from plugins.models import GrantState, Plugin
from plugins.runs import run_guard
from plugins.runs.run_guard import PluginRunGuard
from tables.models import Session
from tables.models.graph_models import PythonNode
from tables.services.run_admission import RunKind, RunSubject, assert_run_admitted

from tests.plugins_tests.suspension_helpers import REACHES, flow, orphan, own, secret_row, set_state

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def weather(running_plugin):
    return running_plugin()


@pytest.fixture
def grant(weather, grant_to, acme):
    """Weather in Acme, suspended."""
    return set_state(grant_to(weather, acme), GrantState.SUSPENDED)


@pytest.fixture
def olga(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    return client


def _run(client, graph):
    return client.post(reverse("run-session"), {"graph_id": graph.pk, "variables": {}}, format="json")


def _flow_subject(graph):
    return RunSubject(RunKind.FLOW, graph.pk, graph.org_id)


# ---- what a run reaches ----


@pytest.mark.parametrize("reach", REACHES.values(), ids=REACHES.keys())
def test_an_organization_flow_using_a_suspended_plugin_s_row_is_refused_before_anything_is_written(
    reach, grant, acme, olga, redis_client_mock
):
    reached = reach(acme)
    own(reached.row, grant)
    # Building some rows publishes on their own (a trigger node's tunnel configuration).
    redis_client_mock.reset_mock()

    response = _run(olga, reached.flow)

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "plugin_suspended"
    assert not Session.objects.exists()
    redis_client_mock.publish.assert_not_called()


@pytest.mark.parametrize("reach", REACHES.values(), ids=REACHES.keys())
def test_the_same_flow_is_admitted_while_the_grant_is_active(
    reach, grant, acme, running_plugin, grant_to, monkeypatch
):
    reached = reach(acme)
    own(reached.row, grant)
    set_state(grant, GrantState.ACTIVE)
    # Another plugin suspended in Acme, owning something this flow never reaches, so the
    # guard walks the run instead of taking the fast path.
    almanac_grant = set_state(grant_to(running_plugin(id="almanac", name="Almanac"), acme), GrantState.SUSPENDED)
    own(flow(acme, "Almanac"), almanac_grant)
    walked = []
    collect = run_guard.RunResourceCollector.collect
    monkeypatch.setattr(
        run_guard.RunResourceCollector, "collect", lambda self, subject: walked.append(subject) or collect(self, subject)
    )

    assert_run_admitted(_flow_subject(reached.flow))
    assert walked == [_flow_subject(reached.flow)]


def test_a_flow_the_plugin_owns_is_refused(grant, acme, olga, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)

    assert _run(olga, forecast).status_code == 409
    assert not Session.objects.exists()


def test_a_flow_with_an_owned_secret_runs_once_the_grant_is_active(grant, acme, olga, redis_client_mock):
    digest = flow(acme, "Digest")
    secret = secret_row(acme, "Weather · LLM key")
    PythonNode.objects.get(graph=digest).python_code.secrets.set([secret])
    own(secret, grant)
    set_state(grant, GrantState.ACTIVE)

    response = _run(olga, digest)

    assert response.status_code == 201, response.content


def test_a_flow_using_nothing_the_plugin_owns_runs_while_it_is_suspended(grant, acme, olga, redis_client_mock):
    own(flow(acme, "Weather forecast"), grant)
    plain = flow(acme, "Plain")

    response = _run(olga, plain)

    assert response.status_code == 201, response.content
    assert Session.objects.filter(graph=plain).count() == 1


@pytest.mark.parametrize("state", [GrantState.GRANTING, GrantState.INSTALL_FAILED, GrantState.SUSPENDED])
def test_every_non_active_state_refuses(grant, acme, state):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    set_state(grant, state)

    with pytest.raises(PluginSuspendedError):
        PluginRunGuard().check(_flow_subject(forecast))


def test_a_row_whose_grant_is_gone_refuses(weather, acme):
    forecast = flow(acme, "Weather forecast")
    orphan(forecast, acme)

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(_flow_subject(forecast))

    assert refused.value.extra_response_data["plugin"] == {"identifier": "weather", "name": "Weather"}
    assert "not active" in str(refused.value.detail)


def test_once_the_plugin_row_is_gone_its_identifier_names_it(weather, grant_to, acme):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant_to(weather, acme))
    Plugin.objects.filter(pk=weather.pk).delete()

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(_flow_subject(forecast))

    assert refused.value.extra_response_data["plugin"] == {"identifier": "weather", "name": "weather"}
    assert refused.value.log_key == "weather:none:removed:0"


def test_with_two_plugins_the_lowest_identifier_names_the_refusal(running_plugin, grant_to, grant, acme):
    almanac = running_plugin(id="almanac", name="Almanac")
    almanac_grant = set_state(grant_to(almanac, acme), GrantState.SUSPENDED)
    reached = REACHES["secret behind an llm config"](acme)
    own(reached.row, grant)
    own(reached.flow, almanac_grant)

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(_flow_subject(reached.flow))

    assert refused.value.extra_response_data["plugin"]["identifier"] == "almanac"


# ---- organizations ----


def test_the_same_plugin_active_in_another_organization_is_unaffected(weather, grant, grant_to, beta):
    beta_grant = grant_to(weather, beta)
    reached = REACHES["agent llm config"](beta)
    own(reached.row, beta_grant)

    assert_run_admitted(_flow_subject(reached.flow))


def test_a_suspension_in_another_organization_never_refuses_this_one(weather, grant_to, acme, beta):
    beta_grant = set_state(grant_to(weather, beta), GrantState.SUSPENDED)
    beta_flow = flow(beta, "Weather forecast")
    own(beta_flow, beta_grant)
    acme_flow = flow(acme, "Weather forecast")

    assert_run_admitted(_flow_subject(acme_flow))
    with pytest.raises(PluginSuspendedError):
        assert_run_admitted(_flow_subject(beta_flow))


# ---- the answer ----


def test_the_refusal_names_the_plugin_and_the_organization_never_the_resource(grant, acme, olga, redis_client_mock):
    reached = REACHES["secret declared by python code"](acme)
    reached.row.name = "very-private-secret-name"
    reached.row.save(update_fields=["name"])
    own(reached.row, grant)

    body = _run(olga, reached.flow).json()

    assert body == {
        "status_code": 409,
        "code": "plugin_suspended",
        "message": 'This run uses resources of the plugin "Weather", which is suspended in this organization.',
        "plugin": {"identifier": "weather", "name": "Weather"},
        "organization": {"id": acme.pk},
    }
    assert "very-private-secret-name" not in str(body)
    assert str(reached.row.pk) not in str(body).replace(str(acme.pk), "")


def test_a_grant_that_is_not_yet_active_says_so(grant, acme):
    forecast = flow(acme, "Weather forecast")
    own(forecast, set_state(grant, GrantState.GRANTING))

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(_flow_subject(forecast))

    assert str(refused.value.detail) == (
        'This run uses resources of the plugin "Weather", which is not active in this organization.'
    )


def test_the_log_key_is_stable_within_a_suspension_and_new_for_the_next(grant, acme):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)

    def log_key():
        with pytest.raises(PluginSuspendedError) as refused:
            PluginRunGuard().check(_flow_subject(forecast))
        return refused.value.log_key

    first = log_key()
    assert log_key() == first
    assert first == f"weather:{grant.pk}:suspended:{int(grant.suspended_at.timestamp())}"
    grant.suspended_at = grant.suspended_at.replace(year=grant.suspended_at.year + 1)
    grant.save(update_fields=["suspended_at"])
    assert log_key() != first


# ---- cost and independence ----


class _CollectorThatMustNotRun:
    def __init__(self):
        raise AssertionError("the fast path walked the run")


@pytest.mark.parametrize("with_active_grant", [False, True], ids=["no grant", "an active grant owning rows"])
def test_without_a_non_active_grant_the_guard_costs_one_query_and_never_walks(
    weather, grant_to, acme, monkeypatch, with_active_grant
):
    forecast = flow(acme, "Weather forecast")
    if with_active_grant:
        own(forecast, grant_to(weather, acme))
    monkeypatch.setattr(run_guard, "RunResourceCollector", _CollectorThatMustNotRun)

    with CaptureQueriesContext(connection) as captured:
        PluginRunGuard().check(_flow_subject(forecast))

    assert len(captured.captured_queries) == 1


def test_a_row_whose_grant_is_gone_leaves_the_fast_path(weather, acme, monkeypatch):
    orphan(flow(acme, "Old forecast"), acme)
    monkeypatch.setattr(run_guard, "RunResourceCollector", _CollectorThatMustNotRun)

    with pytest.raises(AssertionError, match="walked"):
        PluginRunGuard().check(_flow_subject(flow(acme, "Plain")))


def test_the_guard_refuses_with_the_plugin_platform_off(grant, acme, olga, settings, redis_client_mock):
    settings.PLUGINS_ENABLED = False
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)

    assert _run(olga, forecast).status_code == 409
    assert not Session.objects.exists()
