"""Deleting a grant's data at a SuperAdmin's request: the preview, the phrase, and what it starts."""

import threading

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.exceptions import GrantNotPurgeableError, GrantNotSuspendedError
from plugins.lifecycle.grant_purge_service import DELETED_BEFORE_HOOK_FINISHED, GrantPurgeService
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.purge_preview_service import PurgePreviewService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    Plugin,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginServiceAccountKey,
    PluginState,
)
from rest_framework.test import APIClient
from tables.models import DefaultModels, PythonNode, Session, StorageFile
from tables.services.session_manager_service import SessionManagerService

from tests.plugins_tests.suspension_helpers import agent, agent_node_flow, flow, llm_config, own, secret_row, set_state

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

HOOKS = {"install": True, "org_removed": True}


def _url(grant, identifier="weather"):
    return f"/api/admin/plugins/{identifier}/grants/{grant.pk}/"


def _preview(client, grant, identifier="weather"):
    return client.get(f"{_url(grant, identifier)}purge-preview/")


def _purge(client, grant, phrase, identifier="weather"):
    body = {} if phrase is None else {"verification_phrase": phrase}
    return client.delete(_url(grant, identifier), body, format="json")


def _phrase(grant):
    return f"purge-weather-{grant.org.name}"


@pytest.fixture
def weather(weather_backend):
    return weather_backend(hooks=HOOKS)


@pytest.fixture
def grant(weather, superadmin, acme):
    """Weather granted to Acme; its install hook has not run yet."""
    return PluginGrant.objects.select_related("org", "plugin").get(
        pk=PluginGrantService().grant("weather", acme.pk, superadmin).pk
    )


@pytest.fixture
def stopped_sessions(monkeypatch):
    stopped = []

    def publish_stop_session(session_id):
        stopped.append(session_id)
        return 1

    monkeypatch.setattr(SessionManagerService().redis_service, "publish_stop_session", publish_stop_session)
    return stopped


@pytest.fixture
def digest_setup(grant, acme):
    """Olga's Acme: the plugin's key, config, readme and flow, and her own digest flow."""
    key = secret_row(acme, "Weather · LLM key")
    summaries = llm_config(acme, "Weather summaries", api_key_secret=key)
    readme = StorageFile.objects.create(org=acme, path="weather/README.md", name="README.md", parent_path="weather/")
    forecast = flow(acme, "Weather forecast")
    for row in (key, summaries, readme, forecast):
        own(row, grant)
    digest = agent_node_flow(acme, "Daily digest", agent(acme, "digest-writer", llm_config=summaries))
    flow(acme, "Plain")
    session = Session.objects.create(graph=digest, status=Session.SessionStatus.RUN)
    DefaultModels.objects.create(org=acme, agent_llm_config=summaries)
    return {"forecast": forecast, "digest": digest, "session": session, "summaries": summaries}


# ---- the preview ----


def test_the_preview_lists_what_deleting_the_data_removes_and_affects(digest_setup, superadmin_client, grant, acme):
    response = _preview(superadmin_client, grant)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["verification_phrase"] == f"purge-weather-{acme.name}"
    assert body["grant"] == {"id": grant.pk, "state": "granting"}
    assert body["plugin"] == {"identifier": "weather", "name": grant.plugin.name}
    assert body["organization"] == {"id": acme.pk, "name": acme.name}
    assert {row["label"]: row["count"] for row in body["owned_resources"]} == {
        "Files": 1,
        "Flows": 1,
        "LLM configs": 1,
        "Secrets": 1,
    }
    assert [item["name"] for item in body["flows"]["organization"]["items"]] == ["Daily digest"]
    assert [item["name"] for item in body["flows"]["plugin"]["items"]] == ["Weather forecast"]
    assert [item["id"] for item in body["running_sessions"]["items"]] == [digest_setup["session"].pk]
    assert body["default_models"] == [
        {"setting": "agent_llm_config", "config": {"id": digest_setup["summaries"].pk, "name": "Weather summaries"}}
    ]
    assert body["plugin_data"] == "deleted_by_plugin"


def test_the_preview_says_what_happens_to_the_plugin_s_own_data(weather_backend, running_plugin, grant_to, acme, beta, superadmin_client):
    without_hook = weather_backend(hooks={"install": False})
    kept = grant_to(without_hook, acme)
    assert _preview(superadmin_client, kept).json()["plugin_data"] == "kept_until_plugin_deleted"
    frontend_only = running_plugin(id="almanac", name="Almanac")
    nothing = grant_to(frontend_only, beta)
    assert _preview(superadmin_client, nothing, "almanac").json()["plugin_data"] == "none"


def test_the_preview_writes_nothing(digest_setup, superadmin_client, grant):
    counts = (PluginHookJob.objects.count(), PluginActivityEvent.objects.count(), DefaultModels.objects.count())

    _preview(superadmin_client, grant)

    grant.refresh_from_db()
    assert grant.state == GrantState.GRANTING
    assert (PluginHookJob.objects.count(), PluginActivityEvent.objects.count(), DefaultModels.objects.count()) == counts


def _queries_of_a_preview(grant, organization, flow_count):
    secret = secret_row(organization, f"Weather key {flow_count}")
    own(secret, grant)
    for number in range(flow_count):
        digest = flow(organization, f"Digest {flow_count}-{number}")
        PythonNode.objects.get(graph=digest).python_code.secrets.set([secret])
        Session.objects.create(graph=digest, status=Session.SessionStatus.RUN)
        own(flow(organization, f"Forecast {flow_count}-{number}"), grant)
    PurgePreviewService().grant_preview("weather", grant.pk)
    with CaptureQueriesContext(connection) as captured:
        preview = PurgePreviewService().grant_preview("weather", grant.pk)
    return len(captured.captured_queries), preview


def test_the_preview_s_query_count_does_not_grow_with_the_number_of_flows(weather, grant_to, acme, beta):
    few, few_preview = _queries_of_a_preview(grant_to(weather, acme), acme, 5)
    many, many_preview = _queries_of_a_preview(grant_to(weather, beta), beta, 50)

    assert (few_preview.organization_flows.total, many_preview.organization_flows.total) == (5, 50)
    assert few == many


def test_the_preview_of_another_plugin_s_grant_or_an_unknown_one_is_not_found(grant, running_plugin, superadmin_client):
    running_plugin(id="almanac", name="Almanac")

    for response in (
        _preview(superadmin_client, grant, "almanac"),
        _preview(superadmin_client, PluginGrant(pk=grant.pk + 1000)),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "grant_not_found")


# ---- the phrase ----


@pytest.mark.parametrize("phrase", [None, "", "purge-weather", "Purge-weather-Acme-xorg", "purge-weather-Acme-xorg ", 42, ["x"]])
def test_a_missing_different_or_malformed_phrase_changes_nothing(grant, superadmin_client, phrase):
    events = PluginActivityEvent.objects.count()

    response = _purge(superadmin_client, grant, phrase)

    assert response.status_code == 400, response.content
    assert response.json()["code"] in {"invalid_purge_phrase", "invalid"}
    grant.refresh_from_db()
    assert grant.state == GrantState.GRANTING
    assert PluginActivityEvent.objects.count() == events
    assert not PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).exists()
    assert PluginHookJob.objects.get(kind=HookJobKind.INSTALL).state == HookJobState.PENDING


def test_a_non_string_phrase_is_invalid_and_never_echoed(grant, superadmin_client):
    response = _purge(superadmin_client, grant, 424242)

    assert (response.status_code, response.json()["code"]) == (400, "invalid")
    assert "424242" not in response.content.decode()


# ---- the purge ----


def test_the_right_phrase_starts_deleting_and_takes_what_a_suspension_takes(
    grant, superadmin_client, service_account_key, weather, acme, digest_setup, stopped_sessions, django_capture_on_commit_callbacks
):
    service_account_key(weather, acme)
    assert PluginServiceAccountKey.objects.filter(revoked_at__isnull=True).exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = _purge(superadmin_client, grant, _phrase(grant))

    assert response.status_code == 202, response.content
    body = response.json()
    assert (body["state"], body["allowed_actions"]) == ("purging", [])
    assert body["purge_started_at"] is not None
    assert body["org_removed_hook"]["state"] == "pending"
    assert body["org_removed_hook"]["organization"] == {"id": acme.pk, "name": acme.name, "exists": True}
    assert not PluginServiceAccountKey.objects.filter(revoked_at__isnull=True).exists()
    install = PluginHookJob.objects.get(kind=HookJobKind.INSTALL)
    assert (install.state, install.error) == (HookJobState.FAILED, DELETED_BEFORE_HOOK_FINISHED)
    removal = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)
    assert (removal.grant_id, removal.organization_name) == (grant.pk, acme.name)
    assert stopped_sessions == [digest_setup["session"].pk]
    event = PluginActivityEvent.objects.get(action=ActivityAction.GRANT_PURGE_STARTED)
    assert (event.organization_id, event.actor_kind) == (acme.pk, "superadmin")
    assert event.detail == {"reason": "requested", "previous_state": "granting", "owned_resources": 4}
    assert not PluginActivityEvent.objects.filter(action=ActivityAction.GRANT_SUSPENDED).exists()


def test_a_suspended_grant_s_data_is_deleted_without_stopping_anything_again(
    grant, superadmin_client, stopped_sessions, digest_setup, django_capture_on_commit_callbacks, superadmin
):
    with django_capture_on_commit_callbacks(execute=True):
        PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    stopped_sessions.clear()
    Session.objects.filter(pk=digest_setup["session"].pk).update(status=Session.SessionStatus.RUN)

    with django_capture_on_commit_callbacks(execute=True):
        response = _purge(superadmin_client, grant, _phrase(grant))

    assert response.status_code == 202, response.content
    assert stopped_sessions == []
    event = PluginActivityEvent.objects.get(action=ActivityAction.GRANT_PURGE_STARTED)
    assert event.detail["previous_state"] == "suspended"


def test_a_grant_being_deleted_cannot_be_deleted_again(grant, superadmin_client):
    assert _purge(superadmin_client, grant, _phrase(grant)).status_code == 202

    response = _purge(superadmin_client, grant, _phrase(grant))

    assert (response.status_code, response.json()["code"]) == (409, "grant_not_purgeable")


def test_a_grant_of_a_plugin_being_deleted_is_not_purgeable(grant, superadmin_client):
    Plugin.objects.filter(pk=grant.plugin_id).update(state=PluginState.PURGING)

    response = _purge(superadmin_client, grant, _phrase(grant))

    assert (response.status_code, response.json()["code"]) == (409, "grant_not_purgeable")


def test_the_conflict_comes_before_the_phrase(grant, superadmin_client):
    set_state(grant, GrantState.PURGING)

    response = _purge(superadmin_client, grant, "wrong")

    assert response.json()["code"] == "grant_not_purgeable"


def test_another_plugin_s_grant_or_an_unknown_one_is_not_found(grant, running_plugin, superadmin_client):
    running_plugin(id="almanac", name="Almanac")

    for response in (
        _purge(superadmin_client, grant, _phrase(grant), "almanac"),
        _purge(superadmin_client, PluginGrant(pk=grant.pk + 1000), _phrase(grant)),
        _purge(superadmin_client, grant, "wrong", "missing"),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "grant_not_found")
    grant.refresh_from_db()
    assert grant.state == GrantState.GRANTING


def test_an_org_admin_is_refused(grant, client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    assert _purge(client, grant, _phrase(grant)).status_code == 403
    assert _preview(client, grant).status_code == 403
    grant.refresh_from_db()
    assert grant.state == GrantState.GRANTING


def test_an_api_key_is_refused(grant, issue_api_key, superadmin_user):
    raw_key, _ = issue_api_key(user=superadmin_user)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert _purge(client, grant, _phrase(grant)).status_code == 403
    assert _preview(client, grant).status_code == 403


# ---- runs while the data is deleted ----


def test_a_purging_grant_refuses_runs_that_use_what_it_owns_until_they_are_gone(grant, acme, superadmin_client):
    import time

    from django.core.cache import cache
    from plugins.exceptions import PluginSuspendedError
    from plugins.runs.run_guard import PluginRunGuard
    from tables.services.run_admission import RunKind, RunSubject

    secret = secret_row(acme, "Weather · LLM key")
    own(secret, grant)
    digest = flow(acme, "Daily digest")
    PythonNode.objects.get(graph=digest).python_code.secrets.set([secret])
    subject = RunSubject(RunKind.FLOW, digest.pk, acme.pk)
    assert _purge(superadmin_client, grant, _phrase(grant)).status_code == 202

    with pytest.raises(PluginSuspendedError) as refused:
        PluginRunGuard().check(subject)
    assert "not active" in str(refused.value.detail)

    cache.delete_pattern("plugins:purge:failed:*")
    GrantPurgeService().advance(PluginGrant.objects.select_related("plugin", "org").get(pk=grant.pk), time.monotonic() + 30)

    PluginRunGuard().check(subject)


# ---- concurrency ----


@pytest.mark.django_db(transaction=True)
def test_a_purge_racing_a_resume_never_deadlocks_and_the_purge_wins(weather, superadmin, acme):
    """Both lock the plugin, then the grant: one waits for the other. A resume that comes
    second is refused; one that comes first leaves an active grant the purge then takes."""
    grant = PluginGrantService().grant("weather", acme.pk, superadmin)
    PluginSuspensionService().suspend("weather", grant.pk, superadmin)
    start = threading.Barrier(2)
    outcomes = {}

    def run(name, action):
        try:
            start.wait()
            action()
            outcomes[name] = "done"
        except (GrantNotPurgeableError, GrantNotSuspendedError) as error:
            outcomes[name] = error.default_code
        finally:
            connection.close()

    threads = [
        threading.Thread(
            target=run,
            args=(
                "purge",
                lambda: GrantPurgeService().request(
                    "weather", grant.pk, {"verification_phrase": f"purge-weather-{acme.name}"}, superadmin
                ),
            ),
        ),
        threading.Thread(target=run, args=("resume", lambda: PluginSuspensionService().resume("weather", grant.pk, superadmin))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert outcomes["purge"] == "done"
    assert outcomes["resume"] in {"done", "grant_not_suspended"}
    grant.refresh_from_db()
    assert grant.state == GrantState.PURGING
