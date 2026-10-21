"""What suspending a grant would stop, as the SuperAdmin reads it before confirming."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from plugins.exceptions import PluginSuspendedError
from plugins.lifecycle.suspend_preview_service import PREVIEW_LIST_LIMIT, SuspendPreviewService
from plugins.models import GrantState
from plugins.runs.run_guard import PluginRunGuard
from rest_framework.test import APIClient
from tables.models import (
    DefaultModels,
    Graph,
    OpenAIRealtimeConfig,
    RealtimeAgentDefinition,
    RealtimeChannel,
    Session,
    StorageFile,
)
from tables.models.graph_models import PythonNode, ScheduleTriggerNode, TelegramTriggerNode, WebhookTriggerNode
from tables.services.run_admission import RunKind, RunSubject

from tests.plugins_tests.suspension_helpers import REACHES, agent, agent_node_flow, flow, llm_config, own, secret_row, set_state

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

FROZEN_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)


def _preview_url(grant_id, identifier="weather"):
    return f"/api/admin/plugins/{identifier}/grants/{grant_id}/suspend-preview/"


@pytest.fixture
def weather(running_plugin):
    return running_plugin()


@pytest.fixture
def grant(weather, grant_to, acme):
    return grant_to(weather, acme)


@pytest.fixture
def digest_setup(grant, acme):
    """Olga's Acme, as the acceptance walk prepares it."""
    key = secret_row(acme, "Weather · LLM key")
    summaries = llm_config(acme, "Weather summaries", api_key_secret=key)
    readme = StorageFile.objects.create(org=acme, path="weather/README.md", name="README.md", parent_path="weather/")
    forecast = flow(acme, "Weather forecast")
    for row in (key, summaries, readme, forecast):
        own(row, grant)
    ScheduleTriggerNode.objects.create(graph=forecast, node_name="forecast schedule", is_active=False)
    digest = agent_node_flow(acme, "Daily digest", agent(acme, "digest-writer", llm_config=summaries))
    schedule = ScheduleTriggerNode.objects.create(graph=digest, node_name="every 2 minutes", is_active=True)
    plain = flow(acme, "Plain")
    session = Session.objects.create(graph=digest, status=Session.SessionStatus.RUN)
    Session.objects.create(graph=plain, status=Session.SessionStatus.RUN)
    DefaultModels.objects.create(org=acme, agent_llm_config=summaries)
    return {"forecast": forecast, "digest": digest, "plain": plain, "schedule": schedule, "session": session, "summaries": summaries}


def test_the_preview_lists_what_suspending_stops(digest_setup, superadmin_client, grant, acme, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: FROZEN_NOW)

    response = superadmin_client.get(_preview_url(grant.pk))

    assert response.status_code == 200, response.content
    digest, forecast = digest_setup["digest"], digest_setup["forecast"]
    assert response.json() == {
        "grant": {"id": grant.pk, "state": "active"},
        "plugin": {"identifier": "weather", "name": "Weather"},
        "organization": {"id": acme.pk, "name": acme.name},
        "data_kept_until": "2026-11-20T12:00:00Z",
        "owned_resources": [
            {"model": "tables.StorageFile", "label": "Files", "count": 1},
            {"model": "tables.Graph", "label": "Flows", "count": 1},
            {"model": "tables.LLMConfig", "label": "LLM configs", "count": 1},
            {"model": "tables.Secret", "label": "Secrets", "count": 1},
        ],
        "flows": {
            "organization": {"total": 1, "items": [{"id": digest.pk, "name": "Daily digest"}]},
            "plugin": {"total": 1, "items": [{"id": forecast.pk, "name": "Weather forecast"}]},
        },
        "running_sessions": {
            "total": 1,
            "items": [
                {
                    "id": digest_setup["session"].pk,
                    "flow": {"id": digest.pk, "name": "Daily digest"},
                    "status": "run",
                    "created_at": response.json()["running_sessions"]["items"][0]["created_at"],
                }
            ],
        },
        "triggers": {
            "total": 1,
            "items": [
                {
                    "kind": "schedule",
                    "node_id": digest_setup["schedule"].pk,
                    "node_name": "every 2 minutes",
                    "flow": {"id": digest.pk, "name": "Daily digest"},
                }
            ],
        },
        "realtime_agents": {"total": 0, "items": []},
        "voice_channels": {"total": 0, "items": []},
        "default_models": [
            {"setting": "agent_llm_config", "config": {"id": digest_setup["summaries"].pk, "name": "Weather summaries"}}
        ],
    }


def test_webhook_and_telegram_triggers_of_a_stopping_flow_are_listed(grant, acme, superadmin_client):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    hook = WebhookTriggerNode.objects.create(graph=forecast, node_name="hook", python_code=PythonNode.objects.get(graph=forecast).python_code)
    bot = TelegramTriggerNode.objects.create(graph=forecast, node_name="bot")
    WebhookTriggerNode.objects.create(graph=flow(acme, "Plain"), node_name="plain hook", python_code=PythonNode.objects.first().python_code)

    triggers = superadmin_client.get(_preview_url(grant.pk)).json()["triggers"]

    assert triggers["items"] == [
        {"kind": "telegram", "node_id": bot.pk, "node_name": "bot", "flow": {"id": forecast.pk, "name": "Weather forecast"}},
        {"kind": "webhook", "node_id": hook.pk, "node_name": "hook", "flow": {"id": forecast.pk, "name": "Weather forecast"}},
    ]


def test_realtime_agents_and_voice_channels_using_the_plugin_s_rows_are_listed(grant, acme, superadmin_client):
    voice_config = OpenAIRealtimeConfig.objects.create(org=acme, custom_name="Weather voice")
    own(voice_config, grant)
    announcer = agent(acme, "announcer")
    voice = RealtimeAgentDefinition.objects.create(agent_definition=announcer, openai_config=voice_config)
    hotline = RealtimeChannel.objects.create(org=acme, name="Weather hotline", realtime_agent_definition=voice)
    owned_channel = RealtimeChannel.objects.create(org=acme, name="Alerts line")
    own(owned_channel, grant)
    plain_agent = agent(acme, "plain")
    RealtimeAgentDefinition.objects.create(agent_definition=plain_agent)
    RealtimeChannel.objects.create(org=acme, name="Plain line")

    body = superadmin_client.get(_preview_url(grant.pk)).json()

    assert body["realtime_agents"] == {"total": 1, "items": [{"id": announcer.pk, "name": "announcer"}]}
    assert body["voice_channels"] == {
        "total": 2,
        "items": [{"id": owned_channel.pk, "name": "Alerts line"}, {"id": hotline.pk, "name": "Weather hotline"}],
    }


def test_only_default_models_pointing_at_the_plugin_s_configs_are_listed(grant, acme, superadmin_client):
    owned = llm_config(acme, "Weather summaries")
    own(owned, grant)
    DefaultModels.objects.create(org=acme, agent_fcm_llm_config=owned, memory_llm_config=llm_config(acme, "Ours"))

    assert superadmin_client.get(_preview_url(grant.pk)).json()["default_models"] == [
        {"setting": "agent_fcm_llm_config", "config": {"id": owned.pk, "name": "Weather summaries"}}
    ]


def test_the_preview_never_creates_the_default_models_row(grant, acme, superadmin_client):
    own(flow(acme, "Weather forecast"), grant)

    assert superadmin_client.get(_preview_url(grant.pk)).json()["default_models"] == []
    assert not DefaultModels.objects.filter(org=acme).exists()


def test_a_list_holds_at_most_a_hundred_items_and_its_total(grant, acme, superadmin_client):
    for number in range(PREVIEW_LIST_LIMIT + 1):
        own(flow(acme, f"Forecast {number:03}"), grant)

    plugin_flows = superadmin_client.get(_preview_url(grant.pk)).json()["flows"]["plugin"]

    assert plugin_flows["total"] == PREVIEW_LIST_LIMIT + 1
    assert len(plugin_flows["items"]) == PREVIEW_LIST_LIMIT
    assert plugin_flows["items"][0]["name"] == "Forecast 000"


def _queries_of_a_preview(grant, acme, flow_count):
    secret = secret_row(acme, f"Weather · key {flow_count}")
    own(secret, grant)
    voice_config = OpenAIRealtimeConfig.objects.create(org=acme, custom_name=f"Weather voice {flow_count}")
    own(voice_config, grant)
    for number in range(flow_count):
        digest = flow(acme, f"Digest {flow_count}-{number}")
        PythonNode.objects.get(graph=digest).python_code.secrets.set([secret])
        Session.objects.create(graph=digest, status=Session.SessionStatus.RUN)
        ScheduleTriggerNode.objects.create(graph=digest, node_name="schedule", is_active=True)
        own(flow(acme, f"Forecast {flow_count}-{number}"), grant)
        announcer = agent(acme, f"announcer {flow_count}-{number}")
        voice = RealtimeAgentDefinition.objects.create(agent_definition=announcer, openai_config=voice_config)
        RealtimeChannel.objects.create(org=acme, name=f"Hotline {flow_count}-{number}", realtime_agent_definition=voice)
        own(RealtimeChannel.objects.create(org=acme, name=f"Alerts {flow_count}-{number}"), grant)
    SuspendPreviewService().build("weather", grant.pk)
    with CaptureQueriesContext(connection) as captured:
        preview = SuspendPreviewService().build("weather", grant.pk)
    return len(captured.captured_queries), preview


def test_the_query_count_does_not_grow_with_the_number_of_flows_agents_or_channels(weather, grant_to, acme, beta):
    few, few_preview = _queries_of_a_preview(grant_to(weather, acme), acme, 5)
    many, many_preview = _queries_of_a_preview(grant_to(weather, beta), beta, 50)

    assert (few_preview.organization_flows.total, many_preview.organization_flows.total) == (5, 50)
    assert (few_preview.realtime_agents.total, many_preview.realtime_agents.total) == (5, 50)
    assert (few_preview.voice_channels.total, many_preview.voice_channels.total) == (10, 100)
    assert few == many


def test_the_guard_refuses_exactly_the_flows_the_preview_listed(grant, acme, superadmin_client):
    reached = [reach(acme) for reach in REACHES.values()]
    for item in reached[::2]:
        own(item.row, grant)
    own(flow(acme, "Weather forecast"), grant)
    flow(acme, "Plain")

    flows = superadmin_client.get(_preview_url(grant.pk)).json()["flows"]
    listed = {item["id"] for item in flows["organization"]["items"] + flows["plugin"]["items"]}
    set_state(grant, GrantState.SUSPENDED)

    def refused(graph):
        try:
            PluginRunGuard().check(RunSubject(RunKind.FLOW, graph.pk, acme.pk))
        except PluginSuspendedError:
            return True
        return False

    assert listed
    assert {graph.pk for graph in Graph.objects.filter(org=acme) if refused(graph)} == listed


def test_the_preview_works_once_the_grant_is_suspended(grant, acme, superadmin_client):
    own(flow(acme, "Weather forecast"), grant)
    set_state(grant, GrantState.SUSPENDED)
    grant.purge_after = FROZEN_NOW + timedelta(days=30)
    grant.save(update_fields=["purge_after"])

    body = superadmin_client.get(_preview_url(grant.pk)).json()

    assert body["grant"]["state"] == "suspended"
    assert body["flows"]["plugin"]["total"] == 1
    assert body["data_kept_until"] == "2026-11-20T12:00:00Z"


def test_another_plugin_s_grant_or_an_unknown_one_is_not_found(grant, running_plugin, superadmin_client):
    running_plugin(id="almanac", name="Almanac")

    for url in (_preview_url(grant.pk, "almanac"), _preview_url(grant.pk + 1000), _preview_url(grant.pk, "missing")):
        response = superadmin_client.get(url)
        assert (response.status_code, response.json()["code"]) == (404, "grant_not_found"), url


def test_an_org_admin_is_refused(grant, client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    assert client.get(_preview_url(grant.pk)).status_code == 403


def test_an_api_key_is_refused(grant, issue_api_key, superadmin_user):
    raw_key, _ = issue_api_key(user=superadmin_user)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(_preview_url(grant.pk)).status_code == 403
