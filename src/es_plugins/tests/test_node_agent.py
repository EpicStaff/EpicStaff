import tomllib
from pathlib import Path

import pytest
from src.shared.envtools import Env

from es_plugins import AGENT_VERSION
from es_plugins.agent.django_client import DjangoNodeClient
from es_plugins.agent.main import NodeAgent, Reporter
from es_plugins.agent.settings import AgentSettings, AgentSettingsError
from es_plugins.uid_range import UidRange
from tests.helpers import API_URL, NODE_KEY, FakeDjango, desired_state, placement


def test_the_reported_agent_version_is_the_projects():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    assert AGENT_VERSION == project["project"]["version"]


@pytest.fixture
def environment(monkeypatch):
    def with_variables(**overrides) -> Env:
        variables = {
            "PLUGINS_NODE_NAME": "node-1",
            "PLUGINS_NODE_KEY": NODE_KEY,
            "PLUGINS_INTERNAL_API_URL": "http://epicstaff-api:8081/api",
            "PLUGINS_NODE_UID_RANGE": "20000-20999",
            "ES_PLUGINS_DISK_MB_PER_PLUGIN": "2048",
            "ES_PLUGINS_FILES_PER_PLUGIN": "100000",
            **overrides,
        }
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        return Env()

    return with_variables


def test_the_settings_come_from_the_node_variables(environment):
    settings = AgentSettings.from_environment(environment())

    assert settings.api_url == "http://epicstaff-api:8081/api/"
    assert settings.uid_range == UidRange(20000, 20999)
    assert (settings.disk_megabytes_per_plugin, settings.files_per_plugin) == (2048, 100000)


@pytest.mark.parametrize(
    "overrides",
    [
        {"PLUGINS_NODE_KEY": "none"},
        {"PLUGINS_NODE_KEY": "short"},
        {"PLUGINS_NODE_UID_RANGE": "1-5"},
        {"ES_PLUGINS_DISK_MB_PER_PLUGIN": "0"},
        {"ES_PLUGINS_DISK_MB_PER_PLUGIN": "2g"},
        {"ES_PLUGINS_FILES_PER_PLUGIN": "-1"},
        {"ES_PLUGINS_FILES_PER_PLUGIN": "none"},
    ],
)
def test_a_node_without_a_usable_key_or_range_refuses_to_start(environment, overrides):
    with pytest.raises(AgentSettingsError):
        AgentSettings.from_environment(environment(**overrides))


class RecordingReconciler:
    def __init__(self):
        self.applied = []

    async def apply(self, desired):
        self.applied.append(desired)

    def reports(self):
        return []


@pytest.fixture
async def agent(layout, environment):
    fake = FakeDjango()
    fake.desired = desired_state([placement(b"package")])
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=fake.transport)
    reconciler = RecordingReconciler()
    reporter = Reporter(client, reconciler.reports)
    settings = AgentSettings.from_environment(environment())
    node_agent = NodeAgent(settings, layout, client, reconciler, reporter, watchdogs=[])
    yield node_agent, reporter, fake, reconciler
    await client.aclose()


async def test_a_changed_desired_state_is_applied_once(agent):
    node_agent, _, fake, reconciler = agent

    await node_agent.reconcile_once()
    await node_agent.reconcile_once()

    assert reconciler.applied == [fake.desired]


async def test_an_unreachable_django_app_does_not_stop_the_agent(agent):
    node_agent, _, fake, reconciler = agent
    fake.unavailable = True

    await node_agent.reconcile_once()
    fake.unavailable = False
    await node_agent.reconcile_once()

    assert reconciler.applied == [fake.desired]


async def test_the_report_names_the_agent_and_its_placements(agent):
    _, reporter, fake, _ = agent

    await reporter.send_once()

    assert fake.reports[0]["format"] == 1
    assert fake.reports[0]["agent_version"] == AGENT_VERSION
    assert fake.reports[0]["placements"] == []


async def test_a_report_that_cannot_be_sent_is_dropped_without_stopping_the_agent(agent):
    _, reporter, fake, _ = agent
    fake.unavailable = True

    await reporter.send_once()

    assert fake.reports == []

