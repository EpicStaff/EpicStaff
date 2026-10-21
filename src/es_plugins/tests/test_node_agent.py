import asyncio
import tomllib
from pathlib import Path

import pytest
from src.shared.envtools import Env
from src.shared.models.plugin_nodes import RemovalReport

from es_plugins import AGENT_VERSION
from es_plugins.agent.django_client import DjangoNodeClient
from es_plugins.agent import __main__ as agent_entry
from es_plugins.agent.main import NodeAgent, Reporter, run_agent
from es_plugins.agent.settings import AgentSettings, AgentSettingsError
from es_plugins.egress.policy_writer import EgressPolicyError
from es_plugins.uid_range import UidRange
from tests.helpers import API_URL, NODE_KEY, FakeDjango, desired_state, placement
from tests.test_supervisor_backoff import wait_until

DATABASE_ADMIN_PASSWORD = "d" * 64


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
            "PLUGINS_DB_ADMIN_PASSWORD": DATABASE_ADMIN_PASSWORD,
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
    assert settings.database_admin_password == DATABASE_ADMIN_PASSWORD


def test_the_settings_never_show_the_node_key_or_the_database_admin_password(environment):
    shown = repr(AgentSettings.from_environment(environment()))

    assert NODE_KEY not in shown and DATABASE_ADMIN_PASSWORD not in shown


@pytest.mark.parametrize("password", ["none", "too-short-for-a-password", ""])
def test_a_node_without_a_usable_database_admin_password_refuses_to_start(environment, password):
    with pytest.raises(AgentSettingsError, match="PLUGINS_DB_ADMIN_PASSWORD") as refused:
        AgentSettings.from_environment(environment(PLUGINS_DB_ADMIN_PASSWORD=password))

    assert password == "" or password not in str(refused.value)


def test_a_node_without_the_database_admin_password_refuses_to_start(environment, monkeypatch):
    environment()
    monkeypatch.delenv("PLUGINS_DB_ADMIN_PASSWORD")

    with pytest.raises(AgentSettingsError, match="PLUGINS_DB_ADMIN_PASSWORD"):
        AgentSettings.from_environment(Env())


async def test_the_agent_refuses_to_start_without_a_writable_egress_policy_directory(layout, environment):
    layout.agent_directory.mkdir(parents=True)
    layout.egress_policy_directory.rmdir()

    with pytest.raises(EgressPolicyError, match=str(layout.egress_policy_directory)):
        await run_agent(AgentSettings.from_environment(environment()), layout)


def test_an_unwritable_egress_policy_directory_is_a_configuration_error(monkeypatch):
    async def refuse(settings, layout):
        raise EgressPolicyError("the egress policy file /var/lib/es_plugins_egress/policy/passwords cannot be written")

    monkeypatch.setattr(agent_entry, "run_agent", refuse)
    monkeypatch.setattr(agent_entry, "make_not_dumpable", lambda: None)
    monkeypatch.setattr(agent_entry, "configure_logging", lambda component: None)
    monkeypatch.setattr(
        agent_entry.AgentSettings, "from_environment", classmethod(lambda cls: object())
    )

    assert agent_entry.main() == agent_entry.EXIT_CONFIGURATION_ERROR


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
        self.placement_reports = []
        self.removals = []

    async def apply(self, desired):
        self.applied.append(desired)

    def reports(self):
        return list(self.placement_reports)

    def removal_reports(self):
        return list(self.removals)


@pytest.fixture
async def agent(layout, environment):
    fake = FakeDjango()
    fake.desired = desired_state([placement(b"package")])
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=fake.transport)
    reconciler = RecordingReconciler()
    reporter = Reporter(client, reconciler.reports, reconciler.removal_reports)
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



async def test_the_report_carries_the_removals(agent):
    _, reporter, fake, reconciler = agent
    reconciler.removals = [
        RemovalReport(placement_id=7, generation=2, state="failed", last_error="conflict")
    ]

    await reporter.send_once()

    assert fake.reports[0]["removals"] == [
        {"placement_id": 7, "generation": 2, "state": "failed", "last_error": "conflict"}
    ]


@pytest.fixture
async def fake_django():
    fake = FakeDjango()
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=fake.transport)
    yield fake, client
    await client.aclose()


async def test_a_report_that_cannot_be_built_is_skipped_and_the_next_round_goes_out(fake_django):
    fake, client = fake_django
    rounds = [RuntimeError("a placement broke its report"), []]

    def placement_reports():
        outcome = rounds.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    reporter = Reporter(client, placement_reports, lambda: [])

    await reporter.send_once()
    assert fake.reports == []
    await reporter.send_once()
    assert len(fake.reports) == 1


class FlakyClient:
    """django_app's client, failing the first report with an error that is not a network one."""

    def __init__(self, client):
        self._client = client
        self.calls = 0

    async def send_report(self, report):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("not a network error")
        await self._client.send_report(report)


async def test_an_unexpected_error_while_sending_ends_only_that_round(fake_django):
    fake, client = fake_django
    flaky = FlakyClient(client)
    reporter = Reporter(flaky, lambda: [], lambda: [], interval=0.05)

    running = asyncio.create_task(reporter.run())
    try:
        await wait_until(lambda: fake.reports)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    assert flaky.calls >= 2
