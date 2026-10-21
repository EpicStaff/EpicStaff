"""Every kind of run passes the plugin run guard: flows, test runs, realtime, voice channels, code runs, triggers."""

import pytest
from django.urls import reverse
from plugins.models import GrantState
from rest_framework.test import APIClient
from tables.models import (
    OpenAIRealtimeConfig,
    PythonCode,
    PythonCodeResult,
    PythonCodeTool,
    RealtimeAgentDefinition,
    RealtimeChannel,
    Session,
)
from tables.models.graph_models import PythonNode, ScheduleTriggerNode, WebhookTriggerNode
from tables.models.webhook_models import WebhookTrigger
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService

from tests.plugins_tests.suspension_helpers import agent, flow, llm_config, own, secret_row, set_state

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    """Weather in Acme, suspended."""
    return set_state(grant_to(running_plugin(), acme), GrantState.SUSPENDED)


@pytest.fixture
def olga(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    return client


@pytest.fixture
def system_client(issue_api_key):
    raw_key, _ = issue_api_key()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


def _assert_refused(response, acme):
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == "plugin_suspended"
    assert (body["plugin"], body["organization"]) == ({"identifier": "weather", "name": "Weather"}, {"id": acme.pk})


@pytest.fixture
def voice_agent(grant, acme):
    """An agent of Acme's whose LLM config the plugin owns, with a voice."""
    summaries = llm_config(acme, "Weather summaries")
    own(summaries, grant)
    announcer = agent(acme, "announcer", llm_config=summaries)
    RealtimeAgentDefinition.objects.create(agent_definition=announcer)
    return announcer


# ---- flows ----


def test_running_a_flow_with_a_person_s_login_is_refused(grant, acme, olga, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)

    _assert_refused(olga.post(reverse("run-session"), {"graph_id": forecast.pk, "variables": {}}, format="json"), acme)
    assert not Session.objects.exists()


def test_a_trigger_test_run_is_refused(grant, acme, olga, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    node = WebhookTriggerNode.objects.create(
        graph=forecast,
        node_name="hook",
        webhook_trigger=WebhookTrigger.objects.create(path="weather-test-run", org=acme),
        python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main"),
    )

    response = olga.post(
        reverse("run-session-test"),
        {"graph_id": forecast.pk, "node_type": "webhook-trigger", "node_id": node.pk, "payload": {}},
        format="json",
    )

    _assert_refused(response, acme)
    assert not Session.objects.exists()


# ---- realtime and voice channels ----


def test_a_realtime_conversation_with_an_agent_using_the_plugin_s_config_is_refused(voice_agent, acme, olga):
    _assert_refused(olga.post("/api/init-realtime/", {"agent_definition_id": voice_agent.pk}, format="json"), acme)


def test_a_realtime_conversation_whose_voice_config_uses_the_plugin_s_secret_is_refused(grant, acme, olga):
    key = secret_row(acme, "Weather · voice key")
    own(key, grant)
    voice = OpenAIRealtimeConfig.objects.create(org=acme, custom_name="Acme voice", api_key_secret=key)
    announcer = agent(acme, "announcer", llm_config=llm_config(acme, "Acme summaries"))
    RealtimeAgentDefinition.objects.create(agent_definition=announcer, openai_config=voice)

    _assert_refused(olga.post("/api/init-realtime/", {"agent_definition_id": announcer.pk}, format="json"), acme)


def test_the_voice_bridge_s_realtime_start_is_refused_too(voice_agent, acme, system_client):
    _assert_refused(system_client.post("/api/init-realtime/", {"agent_definition_id": voice_agent.pk}, format="json"), acme)


def test_a_voice_channel_the_plugin_owns_is_refused_to_the_realtime_service(grant, acme, system_client):
    channel = RealtimeChannel.objects.create(org=acme, name="Weather hotline")
    own(channel, grant)

    _assert_refused(system_client.get(reverse("realtimechannel-lookup-by-token"), {"token": str(channel.token)}), acme)


def test_an_organization_channel_to_an_agent_using_the_plugin_s_config_is_refused(voice_agent, acme, system_client):
    channel = RealtimeChannel.objects.create(
        org=acme, name="Front desk", realtime_agent_definition=voice_agent.realtime_agent
    )

    _assert_refused(system_client.get(reverse("realtimechannel-lookup-by-token"), {"token": str(channel.token)}), acme)


# ---- code runs ----


def _run_code(client, **body):
    return client.post("/api/run-python-code/", {"variables": {}, **body}, format="json")


def test_running_the_code_of_a_node_of_the_plugin_s_flow_is_refused(grant, acme, olga, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    node = PythonNode.objects.get(graph=forecast)

    _assert_refused(_run_code(olga, target={"type": "python_node", "id": node.pk}), acme)
    _assert_refused(_run_code(olga, python_code_id=node.python_code_id), acme)
    assert not PythonCodeResult.objects.exists()
    redis_client_mock.publish.assert_not_called()


def test_running_an_organization_tool_that_declares_the_plugin_s_secret_is_refused(grant, acme, olga, redis_client_mock):
    secret = secret_row(acme, "Weather · LLM key")
    own(secret, grant)
    code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    code.secrets.set([secret])
    PythonCodeTool.objects.create(org=acme, name="forecast", description="d", python_code=code)

    _assert_refused(_run_code(olga, python_code_id=code.pk), acme)
    assert not PythonCodeResult.objects.exists()


def test_a_node_of_an_organization_flow_runs_when_its_own_code_uses_nothing_the_plugin_owns(
    grant, acme, olga, redis_client_mock
):
    digest = flow(acme, "Daily digest")
    # Another node of the same flow uses the plugin's secret; a code run tests one node.
    other_code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    secret = secret_row(acme, "Weather · LLM key")
    other_code.secrets.set([secret])
    own(secret, grant)
    PythonNode.objects.create(graph=digest, python_code=other_code, node_name="uses the key")
    node = PythonNode.objects.filter(graph=digest).exclude(python_code=other_code).get()

    response = _run_code(olga, target={"type": "python_node", "id": node.pk})

    assert response.status_code == 200, response.content


# ---- triggers ----


def test_a_schedule_of_the_plugin_s_flow_starts_nothing(grant, acme, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    schedule = ScheduleTriggerNode.objects.create(graph=forecast, node_name="every 2 minutes", is_active=True)
    plain_schedule = ScheduleTriggerNode.objects.create(graph=flow(acme, "Plain"), node_name="plain", is_active=True)

    ScheduleTriggerService().handle_schedule_trigger(schedule.pk)
    ScheduleTriggerService().handle_schedule_trigger(plain_schedule.pk)

    assert list(Session.objects.values_list("graph_id", flat=True)) == [plain_schedule.graph_id]
    schedule.refresh_from_db()
    assert (schedule.current_runs, schedule.is_active) == (0, True)


def test_a_webhook_into_the_plugin_s_flow_starts_nothing(grant, acme, redis_client_mock):
    forecast = flow(acme, "Weather forecast")
    own(forecast, grant)
    plain = flow(acme, "Plain")
    trigger = WebhookTrigger.objects.create(path="weather-hook", org=acme)
    for graph in (forecast, plain):
        WebhookTriggerNode.objects.create(
            graph=graph,
            node_name="hook",
            webhook_trigger=trigger,
            python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main"),
        )

    WebhookTriggerService().handle_webhook_trigger(path="weather-hook", payload={})

    assert list(Session.objects.values_list("graph_id", flat=True)) == [plain.pk]
