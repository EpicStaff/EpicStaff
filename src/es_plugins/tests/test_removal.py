"""A plugin's removal from the node, step by step, with the real policy writer and real files.

The database drop and the launcher are stand-ins here; their own tests cover them
(`test_drop_sequence.py`, `test_directory_setup.py`, `test_launcher_protocol.py`).
"""

import asyncio
import json

import pytest
from loguru import logger

from es_plugins.agent.removal import PlacementRemover, RemovalServices
from es_plugins.database.connections import DatabaseUnreachableError
from es_plugins.database.drop_sequence import DatabaseDropError
from es_plugins.egress.policy_writer import HOSTS_FILE_NAME, PASSWORDS_FILE_NAME, EgressPolicyWriter
from tests.helpers import FakeLauncher, RecordingDropper, database_section, removal
from tests.test_supervisor_backoff import wait_until

RETRY_SECONDS = 0.05


class RecordingEgress(EgressPolicyWriter):
    def __init__(self, directory, events):
        super().__init__(directory)
        self._events = events

    async def remove_plugin(self, identifier):
        self._events.append(("egress", identifier))
        await super().remove_plugin(identifier)


class Node:
    """A remover with its stand-ins, the node's trees for two plugins, and the events in order."""

    def __init__(self, layout):
        self.layout = layout
        self.events: list[tuple] = []
        self.dropper = RecordingDropper(self.events)
        self.egress = RecordingEgress(layout.egress_policy_directory, self.events)
        self.launcher = FakeLauncher()
        self.blocking: int | None = None
        self.changes = 0
        self.trees_when_launcher_called: list[bool] = []
        original_remove = self.launcher.remove_plugin

        async def remove_plugin(plugin, uid, *, timeout_seconds):
            self.events.append(("launcher", plugin, uid))
            self.trees_when_launcher_called.append(self.agent_trees_exist(plugin))
            await original_remove(plugin, uid, timeout_seconds=timeout_seconds)

        self.launcher.remove_plugin = remove_plugin

    def services(self) -> RemovalServices:
        return RemovalServices(
            layout=self.layout,
            dropper=self.dropper,
            egress=self.egress,
            launcher=self.launcher,
            prune_downloads=lambda: self.events.append(("prune",)),
            blocking_placement=lambda desired: self.blocking,
            on_change=self._changed,
        )

    def remover(self) -> PlacementRemover:
        return PlacementRemover(self.services(), retry_seconds=RETRY_SECONDS)

    def _changed(self):
        self.changes += 1

    def make_agent_trees(self, plugin: str) -> None:
        layout = self.layout
        venv = layout.plugin_venv(plugin, "0.2.0") / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("")
        logs = layout.plugin_logs(plugin)
        logs.mkdir(parents=True)
        (logs / "current.log").write_text("a line\n")
        unpacked = layout.unpacked_package(plugin, "0.2.0") / "backend"
        unpacked.mkdir(parents=True)
        (unpacked / "requirements.lock").write_text("")
        backups = layout.plugin_backups(plugin)
        backups.mkdir(parents=True, mode=0o700)
        (backups / "20261021T101500Z-u7-pre_upgrade.dump").write_bytes(b"PGDMP")
        (backups / "20261021T101500Z-u7-pre_upgrade.json").write_text("{}")

    def agent_trees_exist(self, plugin: str) -> bool:
        layout = self.layout
        venvs = layout.plugin_venvs(plugin)
        return (
            (venvs.is_dir() and any(venvs.iterdir()))
            or layout.plugin_logs(plugin).exists()
            or (layout.unpack_directory / plugin).exists()
            or layout.plugin_backups(plugin).exists()
        )


@pytest.fixture
async def node(layout):
    for directory in (layout.venvs_root, layout.logs_root, layout.unpack_directory, layout.backups_root):
        directory.mkdir(parents=True, exist_ok=True)
    node = Node(layout)
    await node.egress.start()
    removers: list[PlacementRemover] = []
    original = node.remover

    def remover():
        made = original()
        removers.append(made)
        return made

    node.remover = remover
    yield node
    for made in removers:
        await made.close()


def state_of(remover: PlacementRemover, placement_id: int = 7):
    return next(
        ((report.state, report.last_error) for report in remover.reports() if report.placement_id == placement_id),
        None,
    )


async def test_the_steps_run_in_order_and_end_removed(node):
    node.make_agent_trees("weather")
    remover = node.remover()

    remover.apply([removal(database=database_section())], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    assert node.events == [
        ("drop", "plugin_weather"),
        ("egress", "weather"),
        ("prune",),
        ("launcher", "weather", 20001),
    ]
    assert node.trees_when_launcher_called == [False]


async def test_without_a_database_nothing_is_dropped(node):
    remover = node.remover()

    remover.apply([removal()], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    assert node.dropper.drops == []


async def test_it_waits_while_a_controller_still_runs_the_plugin(node):
    node.blocking = 9
    remover = node.remover()

    remover.apply([removal()], {})
    await asyncio.sleep(0.2)

    state, last_error = state_of(remover)
    assert state == "removing"
    assert "placement 9" in last_error
    assert node.events == []

    node.blocking = None
    remover.notice_change()
    await wait_until(lambda: state_of(remover) == ("removed", None))


async def test_the_plugins_password_and_host_list_go_and_the_other_plugins_stay(node, layout):
    await node.egress.write_hosts({"weather": ["api.open-meteo.com"], "notes": ["api.example.org"]})
    await node.egress.issue_password("weather")
    await node.egress.issue_password("notes")
    remover = node.remover()

    remover.apply([removal()], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    policy = layout.egress_policy_directory
    assert json.loads((policy / HOSTS_FILE_NAME).read_text()) == {"notes": ["api.example.org"]}
    passwords = (policy / PASSWORDS_FILE_NAME).read_text()
    assert passwords.startswith("notes:") and "weather:" not in passwords


async def test_the_agents_trees_of_the_plugin_go_and_another_plugins_stay(node, layout, tmp_path):
    node.make_agent_trees("weather")
    node.make_agent_trees("notes")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("not the plugin's")
    (layout.plugin_logs("weather") / "link").symlink_to(outside)
    (layout.plugin_venvs("weather") / "link").symlink_to(outside)
    (layout.plugin_backups("weather") / "link.dump").symlink_to(outside / "keep.txt")
    remover = node.remover()

    remover.apply([removal()], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    assert not node.agent_trees_exist("weather")
    # The launcher removes the (now empty) venvs directory itself.
    assert list(layout.plugin_venvs("weather").iterdir()) == []
    assert node.agent_trees_exist("notes")
    assert (layout.plugin_venv("notes", "0.2.0") / "bin" / "python").exists()
    assert (outside / "keep.txt").read_text() == "not the plugin's"
    # A deleted plugin keeps no backups; another plugin keeps its own.
    assert not layout.plugin_backups("weather").exists()
    assert sorted(path.name for path in layout.plugin_backups("notes").iterdir()) == [
        "20261021T101500Z-u7-pre_upgrade.dump",
        "20261021T101500Z-u7-pre_upgrade.json",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached: timeout"),
        DatabaseDropError("database", "database plugin_weather is still in use", temporary=True),
    ],
)
async def test_a_temporary_failure_is_retried_while_it_reports_removing(node, failure):
    node.dropper.failures = [failure]
    remover = node.remover()
    changes = []

    remover.apply([removal(database=database_section())], {})
    await wait_until(lambda: (changes.append(state_of(remover)), state_of(remover) == ("removed", None))[1])

    assert ("removing", str(failure)) in changes
    assert len(node.dropper.drops) == 2


async def test_an_unreachable_launcher_is_retried(node):
    node.launcher.unavailable_removals = 1
    remover = node.remover()

    remover.apply([removal()], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    assert [event for event in node.events if event[0] == "launcher"] == [
        ("launcher", "weather", 20001),
        ("launcher", "weather", 20001),
    ]


@pytest.mark.parametrize(
    ("fail", "expected"),
    [
        ("conflict", "plugins_db has role"),
        ("sql", "[42501] permission denied"),
        ("launcher", "a process survived"),
    ],
)
async def test_a_permanent_failure_reports_failed_until_a_new_generation(node, fail, expected):
    if fail == "conflict":
        node.dropper.failures = [DatabaseDropError("conflict", 'plugins_db has role "weather_owner" ...')]
    elif fail == "sql":
        node.dropper.failures = [DatabaseDropError("database", "[42501] permission denied")]
    else:
        node.launcher.refuse_removal = "a process survived"
    remover = node.remover()

    remover.apply([removal(database=database_section())], {})
    await wait_until(lambda: (state_of(remover) or ("",))[0] == "failed")
    await asyncio.sleep(RETRY_SECONDS * 4)

    state, last_error = state_of(remover)
    assert state == "failed" and expected in last_error
    attempts = len([event for event in node.events if event[0] == "drop"])
    assert attempts == 1

    remover.apply([removal(database=database_section())], {})
    await asyncio.sleep(RETRY_SECONDS * 2)
    assert state_of(remover)[0] == "failed"

    node.launcher.refuse_removal = None
    remover.apply([removal(database=database_section(), generation=1)], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))
    assert remover.reports()[0].generation == 1


async def test_after_an_agent_restart_a_finished_removal_completes_at_once(node):
    first = node.remover()
    first.apply([removal(database=database_section())], {})
    await wait_until(lambda: state_of(first) == ("removed", None))
    await first.close()

    node.dropper.nothing_left = True
    again = node.remover()
    again.apply([removal(database=database_section())], {})
    await wait_until(lambda: state_of(again) == ("removed", None))


async def test_removed_is_reported_while_the_removal_is_wanted_and_then_forgotten(node):
    remover = node.remover()
    remover.apply([removal()], {})
    await wait_until(lambda: state_of(remover) == ("removed", None))

    remover.apply([removal()], {})
    assert state_of(remover) == ("removed", None)

    remover.apply([], {})
    assert remover.reports() == []


async def test_the_drop_holds_the_closed_controllers_database_lock(node):
    held = asyncio.Lock()

    class ClosedDatabase:
        lock = held

    await held.acquire()
    remover = node.remover()
    remover.apply([removal(database=database_section())], {7: ClosedDatabase()})
    await asyncio.sleep(0.2)
    assert node.dropper.drops == []

    held.release()
    await wait_until(lambda: state_of(remover) == ("removed", None))


async def test_no_password_reaches_a_log_line(node):
    password = await node.egress.issue_password("weather")
    node.dropper.failures = [DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached")]
    lines = []
    sink = logger.add(lines.append, format="{message}", level="DEBUG")
    try:
        remover = node.remover()
        remover.apply([removal(database=database_section())], {})
        await wait_until(lambda: state_of(remover) == ("removed", None))
    finally:
        logger.remove(sink)

    assert any(line.startswith("plugins.removal.started plugin=weather placement=7") for line in lines)
    assert any("plugins.removal.database_dropped plugin=weather placement=7 databases=1 roles=3" in line for line in lines)
    assert any(line.startswith("plugins.removal.done plugin=weather placement=7") for line in lines)
    assert any("plugins.removal.failed plugin=weather reason=unreachable" in line for line in lines)
    assert not [line for line in lines if password in line or "$2b$" in line]
