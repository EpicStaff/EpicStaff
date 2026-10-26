"""The reconciler against django_app (`httpx.MockTransport`) and the launcher stand-in.

The plugin's process is a real child answering the health check; the venv build is
recorded instead of run (it has its own tests).
"""

import asyncio
import base64
import errno
import hashlib
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
from loguru import logger
from src.shared.models.plugin_nodes import LedgerEntry

from es_plugins.agent import reconciler as reconciler_module
from es_plugins.agent.django_client import DjangoNodeClient
from es_plugins.agent.main import prepare_agent_directories
from es_plugins.agent.port_reservation import PortReservation
from es_plugins.agent.reconciler import AgentServices, Reconciler
from es_plugins.database.backup_store import BackupStore
from es_plugins.database.connections import DatabaseProvisioningError, DatabaseUnreachableError
from es_plugins.egress.policy_writer import HOSTS_FILE_NAME, PASSWORDS_FILE_NAME, EgressPolicyWriter
from es_plugins.health.health_checker import HealthChecker
from es_plugins.hooks.hook_caller import PluginHookCaller
from es_plugins.hooks.hook_runner import RESTARTED_DURING_HOOK, STOPPED_DURING_HOOK
from es_plugins.node_disk import INSTALL_RESERVE_BYTES, NodeDisk
from es_plugins.packages.package_fetcher import PackageFetcher
from es_plugins.supervisor.process_supervisor import ProcessSupervisor
from tests.helpers import (
    API_URL,
    HOOK_ASSERTION,
    NODE_KEY,
    SERVICE_ACCOUNT_KEY,
    FakeDjango,
    FakeLauncher,
    RecordingBackups,
    RecordingDropper,
    RecordingProvisioner,
    RecordingRestores,
    backend_wheels,
    database_section,
    desired_state,
    free_port,
    free_ports,
    hook_body,
    hook_invocation,
    hook_job,
    manifest,
    package_files,
    placement,
    removal,
    runtime_file_document,
    service_account,
    write_package,
)
from tests.test_supervisor_backoff import wait_until

pytestmark = pytest.mark.linux

UID = 20001


class Volume:
    """The node volume's free space, as the test sets it."""

    def __init__(self):
        self.free_bytes = 100 * INSTALL_RESERVE_BYTES

    def __call__(self, path):
        return SimpleNamespace(f_bavail=self.free_bytes // 4096, f_frsize=4096, f_favail=10**7, f_files=10**8)


class RecordingVenvBuilder:
    def __init__(self):
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        assert (request.backend / "requirements.lock").is_file()
        python = request.venv / "bin" / "python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("")
        return python


@pytest.fixture
def package_bytes(tmp_path):
    files = package_files(backend_wheels(tmp_path / "wheels"))
    return write_package(tmp_path / "weather.esplugin", files).read_bytes()


@pytest.fixture
def newer_package_bytes(tmp_path):
    files = package_files(backend_wheels(tmp_path / "wheels"), manifest(version="0.3.0"))
    return write_package(tmp_path / "weather-0.3.0.esplugin", files, version="0.3.0").read_bytes()


def port_is_free(port: int) -> bool:
    """Whether no socket listens on `port` (connections closing in TIME_WAIT do not count)."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", port))
        except OSError as error:
            assert error.errno == errno.EADDRINUSE
            return False
        return True


class RecordingEgress(EgressPolicyWriter):
    """The real policy writer, noting when a password is issued next to the launcher's steps."""

    def __init__(self, directory, events):
        super().__init__(directory)
        self._events = events

    async def issue_password(self, identifier):
        self._events.append(("issue_password", identifier))
        return await super().issue_password(identifier)


@pytest.fixture
async def node(tmp_path, layout, package_bytes):
    layout.agent_directory.mkdir(parents=True)
    prepare_agent_directories(layout)
    django = FakeDjango()
    django.packages[12] = package_bytes
    django.runtime_files[7] = runtime_file_document()
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=django.transport)
    launcher = FakeLauncher()
    launcher.hook_record = tmp_path / "hooks.jsonl"
    provisioner = RecordingProvisioner(launcher.operations)
    dropper = RecordingDropper(launcher.operations)
    egress = RecordingEgress(layout.egress_policy_directory, launcher.operations)
    await egress.start()
    venv_builder = RecordingVenvBuilder()
    health_checker = HealthChecker()
    hook_caller = PluginHookCaller()
    changes = []
    port, other_port = free_ports(2)
    volume = Volume()
    ports = PortReservation([port, other_port])
    ports.reserve()
    layout.backups_root.mkdir(mode=0o700)
    backup_store = BackupStore(layout)
    backups = RecordingBackups(backup_store, launcher.operations)
    restores = RecordingRestores(backups, launcher.operations)
    desired_state_requests = []
    services = AgentServices(
        layout=layout,
        django=client,
        fetcher=PackageFetcher(client, layout.downloads_directory),
        launcher=launcher,
        health_checker=health_checker,
        ports=ports,
        disk=NodeDisk(layout.data_root, statvfs=volume),
        hook_caller=hook_caller,
        provisioner=provisioner,
        dropper=dropper,
        egress=egress,
        backup_store=backup_store,
        backups=backups,
        restores=restores,
        on_change=lambda: changes.append(reconciler.reports()),
        request_desired_state=lambda: desired_state_requests.append(True),
        interpreter_for=lambda python: Path(sys.executable),
        venv_builder=venv_builder,
    )
    reconciler = Reconciler(services)

    def desired(package=package_bytes, **overrides):
        return desired_state(
            [placement(package, **{"runtime__port": port, "uid": UID, **overrides})]
        )

    desired.port, desired.other_port = port, other_port
    desired.package_bytes = package_bytes
    desired.volume = volume
    desired.changes = changes
    desired.services = services
    desired.provisioner = provisioner
    desired.dropper = dropper
    desired.backups = backups
    desired.restores = restores
    desired.desired_state_requests = desired_state_requests
    yield reconciler, django, launcher, venv_builder, desired
    await reconciler.close()
    ports.close()
    launcher.stop_all()
    await health_checker.aclose()
    await hook_caller.aclose()
    await client.aclose()


def proxy_password(layout, spawned) -> str:
    """The proxy password in the process's environment, checked against the password file."""
    password = spawned["environment"]["HTTPS_PROXY"].removeprefix("http://weather:").split("@")[0]
    lines = dict(
        line.split(":", 1)
        for line in (layout.egress_policy_directory / PASSWORDS_FILE_NAME).read_text().splitlines()
    )
    assert bcrypt.checkpw(password.encode(), lines["weather"].encode())
    return password


def listed_passwords(layout) -> list[str]:
    text = (layout.egress_policy_directory / PASSWORDS_FILE_NAME).read_text()
    return [line.split(":", 1)[0] for line in text.splitlines()]


def running(reconciler):
    reports = reconciler.reports()
    return bool(reports) and (reports[0].observed_state, reports[0].health) == ("running", "ok")


async def test_a_new_placement_is_installed_configured_and_started(node, layout):
    reconciler, django, launcher, venv_builder, desired = node

    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))

    operations = [operation[0] for operation in launcher.operations]
    assert operations.index("install_code") < operations.index("write_runtime_file")
    assert operations.index("write_runtime_file") < operations.index("spawn")
    assert json.loads(launcher.runtime_files["weather"]) == django.runtime_files[7]
    venv = layout.plugin_venv("weather", "0.2.0")
    assert venv_builder.requests[0].source_path == layout.plugin_source("weather", "0.2.0")
    spawned = launcher.spawned[0]
    assert spawned["argv"] == [str(venv / "bin" / "python"), "-I", "-m", "epicstaff_plugin.serve"]
    assert spawned["nice"] == 0
    assert spawned["environment"] == {
        "PORT": spawned["environment"]["PORT"],
        "USER": "weather",
        "LOGNAME": "weather",
        "HOME": str(layout.plugin_home("weather")),
        "TMPDIR": str(layout.plugin_temporary_directory("weather")),
        "PATH": f"{venv}/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "EPICSTAFF_PLUGIN_IDENTIFIER": "weather",
        "EPICSTAFF_PLUGIN_VERSION": "0.2.0",
        "EPICSTAFF_PLUGIN_ENTRYPOINT": "weather_plugin.app:app",
        "EPICSTAFF_PLUGIN_RUNTIME_FILE": str(layout.runtime_file("weather")),
        "EPICSTAFF_API_URL": "http://epicstaff-api:8081/api/",
        "EPICSTAFF_PUBLIC_URL": "https://epicstaff.example.com",
        "EPICSTAFF_PLUGIN_PUBLIC_URL": "https://weather.plugins.example.com",
        **dict.fromkeys(
            ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"),
            f"http://weather:{proxy_password(layout, spawned)}@plugins_egress:3128",
        ),
        "NO_PROXY": "epicstaff-api,localhost,127.0.0.1,::1",
        "no_proxy": "epicstaff-api,localhost,127.0.0.1,::1",
    }
    assert not any("secret" in argument for argument in spawned["argv"])
    assert reconciler.reports()[0].database is None
    report = reconciler.reports()[0]
    assert (report.observed_version, report.applied_restart_generation) == ("0.2.0", 0)
    assert report.applied_credentials_revision == "c" * 64
    assert not layout.unpacked_package("weather", "0.2.0").exists()


async def test_the_same_desired_state_again_changes_nothing(node):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    operations_before = list(launcher.operations)

    await reconciler.apply(desired())
    await reconciler.apply(desired())

    assert launcher.operations == operations_before


async def test_a_new_credentials_revision_only_rewrites_the_runtime_file(node):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    django.credentials_revisions[7] = "d" * 64
    django.runtime_files[7] = runtime_file_document(settings={"units": "metric", "rotated": True})

    await reconciler.apply(desired(credentials_revision="d" * 64))
    await wait_until(lambda: reconciler.reports()[0].applied_credentials_revision == "d" * 64)

    assert json.loads(launcher.runtime_files["weather"])["settings"]["rotated"] is True
    assert len(launcher.spawned) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"settings_revision": 1},
        {"restart_generation": 1},
        {"runtime__memory_mb": 128},
        {"runtime__cpu_priority": "low"},
        {"runtime__port": "another"},
        {"package": "newer"},
    ],
)
async def test_a_change_that_needs_a_new_process_restarts_it(
    node, newer_package_bytes, change
):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    django.settings_revisions[7] = change.get("settings_revision", 0)
    if change.get("runtime__port") == "another":
        change = {"runtime__port": desired.other_port}
    if change.get("package") == "newer":
        django.packages[13] = newer_package_bytes
        change = {"package": newer_package_bytes, "package__package_id": 13, "version": "0.3.0"}

    await reconciler.apply(desired(**change))
    await wait_until(lambda: len(launcher.spawned) == 2)
    await wait_until(lambda: running(reconciler))

    assert [operation[0] for operation in launcher.operations].count("write_runtime_file") == 2
    if change.get("runtime__cpu_priority") == "low":
        assert launcher.spawned[1]["nice"] == 10
    if "runtime__port" in change:
        # The new process serves the new port; the agent still holds the old one.
        assert launcher.spawned[1]["environment"]["PORT"] == str(change["runtime__port"])
        assert not port_is_free(desired.port)
    if "package" in change:
        assert reconciler.reports()[0].observed_version == "0.3.0"
        assert launcher.spawned[1]["argv"][0].endswith("/weather/0.3.0/bin/python")


async def test_newer_settings_that_arrive_with_a_credentials_rewrite_still_restart_later(node):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    # The settings change lands in django_app between the desired state and the fetch: the
    # credentials-only rewrite already writes the new settings, but the process still runs
    # with the old ones.
    django.credentials_revisions[7] = "d" * 64
    django.settings_revisions[7] = 1

    await reconciler.apply(desired(credentials_revision="d" * 64))
    await wait_until(lambda: reconciler.reports()[0].applied_credentials_revision == "d" * 64)
    assert len(launcher.spawned) == 1
    assert reconciler.reports()[0].applied_settings_revision == 0

    await reconciler.apply(desired(credentials_revision="d" * 64, settings_revision=1))
    await wait_until(lambda: len(launcher.spawned) == 2)
    await wait_until(lambda: running(reconciler))

    assert reconciler.reports()[0].applied_settings_revision == 1


async def test_the_agent_keeps_holding_a_port_after_its_placement_goes(node):
    reconciler, _, launcher, _, desired = node

    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    assert not port_is_free(desired.port)

    await reconciler.apply(desired_state([]))

    # It no longer takes connections, and no plugin can take it before the next placement
    # that is given it.
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", desired.port), timeout=5)
    assert not port_is_free(desired.port)


async def test_a_port_that_is_not_one_of_the_nodes_is_retried_and_nothing_is_installed(
    node, monkeypatch
):
    monkeypatch.setattr(reconciler_module, "TRANSIENT_RETRY_SECONDS", 0.2)
    reconciler, django, launcher, _, desired = node

    await reconciler.apply(desired(runtime__port=free_port()))
    await wait_until(lambda: reconciler.reports()[0].last_error is not None)

    assert "is not one of this node's ports" in reconciler.reports()[0].last_error
    assert not [request for request in django.requests if "packages" in request.url.path]
    assert launcher.spawned == []


async def test_nothing_is_downloaded_below_the_install_reserve_until_a_restart_with_room(node):
    reconciler, django, launcher, venv_builder, desired = node
    desired.volume.free_bytes = INSTALL_RESERVE_BYTES - 1

    await reconciler.apply(desired())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")

    assert reconciler.reports()[0].last_error.startswith("the node's disk has only 2047 MB free")
    assert not [request for request in django.requests if "packages" in request.url.path]
    assert launcher.spawned == []
    assert venv_builder.requests == []

    desired.volume.free_bytes = 100 * INSTALL_RESERVE_BYTES
    await reconciler.apply(desired(restart_generation=1))
    await wait_until(lambda: running(reconciler))


async def test_a_venv_is_not_built_below_the_install_reserve(node, monkeypatch):
    reconciler, django, launcher, venv_builder, desired = node
    real_fetch = reconciler_module.PackageFetcher.fetch

    async def fetch_then_fill_the_disk(fetcher, package):
        path = await real_fetch(fetcher, package)
        desired.volume.free_bytes = INSTALL_RESERVE_BYTES - 1
        return path

    monkeypatch.setattr(reconciler_module.PackageFetcher, "fetch", fetch_then_fill_the_disk)

    await reconciler.apply(desired())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")

    assert "installing needs 2048 MB" in reconciler.reports()[0].last_error
    assert venv_builder.requests == []
    assert launcher.spawned == []


def hook_calls(launcher) -> list[dict]:
    """The hook calls the plugin stand-ins received, in order."""
    if not launcher.hook_record.exists():
        return []
    return [json.loads(line) for line in launcher.hook_record.read_text().splitlines()]


def with_service_accounts(*organization_ids, identifier="weather") -> dict:
    return runtime_file_document(
        identifier,
        service_accounts={str(organization_id): service_account() for organization_id in organization_ids},
    )


async def test_a_hook_is_called_only_once_the_process_answers_its_health_check(node):
    reconciler, django, launcher, _, desired = node
    launcher.healthy_after = 1.5
    django.runtime_files[7] = with_service_accounts(3)
    django.hook_invocations[41] = hook_invocation()
    state_at_claim = []
    django.on_claim = lambda job_id: state_at_claim.append(
        (reconciler.reports()[0].observed_state, reconciler.reports()[0].health)
    )

    await reconciler.apply(desired(hook_jobs=[hook_job()]))
    await wait_until(lambda: django.hook_results)

    assert state_at_claim == [("running", "ok")]
    [call] = hook_calls(launcher)
    assert call["path"] == "/_epicstaff/hooks/install"
    assert (call["hook"], call["content_type"]) == (HOOK_ASSERTION, "application/json")
    assert base64.b64decode(call["body"]) == hook_body().encode()
    assert django.hook_results[0][0] == 41
    assert (django.hook_results[0][1]["outcome"], django.hook_results[0][1]["attempt"]) == ("succeeded", 1)


async def test_a_hook_waits_for_a_runtime_file_of_the_desired_revision_that_lists_its_organization(node):
    reconciler, django, launcher, _, desired = node
    django.hook_invocations[41] = hook_invocation()

    # Running and healthy, but the runtime file holds no service account for organization 3.
    await reconciler.apply(desired(hook_jobs=[hook_job()]))
    await wait_until(lambda: running(reconciler))
    await asyncio.sleep(0.5)
    assert django.requests_to("claim") == []

    # The rewritten file lists the organization, but django_app answered with another revision
    # than the desired state names.
    django.runtime_files[7] = with_service_accounts(3)
    django.credentials_revisions[7] = "e" * 64
    await reconciler.apply(desired(hook_jobs=[hook_job()], credentials_revision="d" * 64))
    await wait_until(lambda: SERVICE_ACCOUNT_KEY.encode() in launcher.runtime_files["weather"])
    await asyncio.sleep(0.5)
    assert django.requests_to("claim") == []

    await reconciler.apply(desired(hook_jobs=[hook_job()], credentials_revision="e" * 64))
    await wait_until(lambda: django.hook_results)

    assert django.requests_to("claim") == [41]
    assert len(launcher.spawned) == 1


async def test_a_placement_runs_one_hook_at_a_time_oldest_first(node):
    reconciler, django, launcher, _, desired = node
    launcher.hook_delay = 0.5
    django.runtime_files[7] = with_service_accounts(3, 4)
    django.hook_invocations[41] = hook_invocation(41, 3)
    django.hook_invocations[42] = hook_invocation(42, 4)

    await reconciler.apply(desired(hook_jobs=[hook_job(41, 3), hook_job(42, 4)]))
    await wait_until(lambda: len(django.hook_results) == 2)

    hook_requests = [
        (request.url.path.split("/")[-3], request.url.path.split("/")[-2])
        for request in django.requests
        if "/hook-jobs/" in request.url.path
    ]
    assert hook_requests == [("41", "claim"), ("41", "result"), ("42", "claim"), ("42", "result")]
    first, second = hook_calls(launcher)
    assert second["started"] - first["started"] >= 0.5


async def test_placements_run_their_hooks_in_parallel(node, tmp_path):
    reconciler, django, launcher, _, desired = node
    launcher.hook_delay = 5.0
    other_files = package_files(
        backend_wheels(tmp_path / "other-wheels"), manifest(identifier="other")
    )
    other_bytes = write_package(
        tmp_path / "other.esplugin", other_files, identifier="other"
    ).read_bytes()
    django.packages[13] = other_bytes
    django.runtime_files[7] = with_service_accounts(3)
    django.runtime_files[8] = with_service_accounts(3, identifier="other")
    django.hook_invocations[41] = hook_invocation(41, 3)
    django.hook_invocations[51] = hook_invocation(51, 3, identifier="other")

    await reconciler.apply(
        desired_state(
            [
                placement(
                    desired.package_bytes,
                    runtime__port=desired.port,
                    uid=UID,
                    hook_jobs=[hook_job(41, 3)],
                ),
                placement(
                    other_bytes,
                    placement_id=8,
                    package_id=13,
                    identifier="other",
                    uid=UID + 1,
                    runtime__port=desired.other_port,
                    hook_jobs=[hook_job(51, 3)],
                ),
            ]
        )
    )
    await wait_until(lambda: len(django.hook_results) == 2, timeout=20)

    first, second = sorted(hook_calls(launcher), key=lambda call: call["started"])
    assert {base64.b64decode(call["body"]) for call in (first, second)} == {
        hook_body(41, 3).encode(),
        hook_body(51, 3, identifier="other").encode(),
    }
    # The second call began while the first plugin still held its hook.
    assert second["started"] < first["started"] + launcher.hook_delay


async def test_converge_goes_on_while_a_hook_runs(node):
    reconciler, django, launcher, _, desired = node
    launcher.hook_delay = 5.0
    django.runtime_files[7] = with_service_accounts(3)
    django.hook_invocations[41] = hook_invocation()
    await reconciler.apply(desired(hook_jobs=[hook_job()]))
    await wait_until(lambda: hook_calls(launcher))

    django.credentials_revisions[7] = "d" * 64
    django.runtime_files[7] = {**with_service_accounts(3), "settings": {"units": "imperial"}}
    await reconciler.apply(desired(hook_jobs=[hook_job()], credentials_revision="d" * 64))
    await wait_until(lambda: reconciler.reports()[0].applied_credentials_revision == "d" * 64)

    assert django.hook_results == []
    assert json.loads(launcher.runtime_files["weather"])["settings"] == {"units": "imperial"}
    await wait_until(lambda: django.hook_results)
    assert django.hook_results[0][1]["outcome"] == "succeeded"


async def test_a_restart_during_a_hook_reports_it_failed(node):
    reconciler, django, launcher, _, desired = node
    launcher.hook_delay = 30.0
    django.runtime_files[7] = with_service_accounts(3)
    django.hook_invocations[41] = hook_invocation(timeout_seconds=60)
    await reconciler.apply(desired(hook_jobs=[hook_job()]))
    await wait_until(lambda: hook_calls(launcher))

    await reconciler.apply(desired(hook_jobs=[hook_job()], restart_generation=1))
    await wait_until(lambda: django.hook_results)

    result = django.hook_results[0][1]
    assert (result["outcome"], result["error"], result["http_status"]) == (
        "failed",
        RESTARTED_DURING_HOOK,
        None,
    )
    assert result["duration_ms"] < 30_000
    await wait_until(lambda: len(launcher.spawned) == 2 and running(reconciler))


async def test_a_stop_during_a_hook_reports_it_failed_as_stopped(node):
    reconciler, django, launcher, _, desired = node
    launcher.hook_delay = 30.0
    django.runtime_files[7] = with_service_accounts(3)
    django.hook_invocations[41] = hook_invocation(timeout_seconds=60)
    await reconciler.apply(desired(hook_jobs=[hook_job()]))
    await wait_until(lambda: hook_calls(launcher))

    await reconciler.apply(desired(hook_jobs=[hook_job()], desired_state="stopped"))
    await wait_until(lambda: django.hook_results)

    result = django.hook_results[0][1]
    assert (result["outcome"], result["error"]) == ("failed", STOPPED_DURING_HOOK)
    await wait_until(lambda: reconciler.reports()[0].observed_state == "stopped")
    assert len(launcher.spawned) == 1


async def test_no_key_assertion_or_hook_body_reaches_a_log_line_or_a_report(node):
    reconciler, django, launcher, _, desired = node
    django.runtime_files[7] = with_service_accounts(3)
    django.hook_invocations[41] = hook_invocation()
    lines = []
    sink = logger.add(lines.append, format="{message} {exception}", level="DEBUG")
    try:
        await reconciler.apply(desired(hook_jobs=[hook_job()]))
        await wait_until(lambda: django.hook_results)
    finally:
        logger.remove(sink)

    assert any("hook job 41" in line for line in lines)
    reports = [report.model_dump_json() for reports in desired.changes for report in reports]
    for secret in (SERVICE_ACCOUNT_KEY, HOOK_ASSERTION, hook_body(), '"job_id":41'):
        assert not [line for line in lines if secret in line], secret
        assert not [report for report in reports if secret in report], secret
    assert SERVICE_ACCOUNT_KEY not in json.dumps(django.hook_results)


APP_PASSWORD = "A" * 21 + "-_" + "z" * 20
DATABASE_MIGRATIONS = {"002_more.sql": b"SELECT 2;\n", "001_places.sql": b"CREATE TABLE places (id int);\n"}


@pytest.fixture
def database_package_bytes(tmp_path):
    files = package_files(backend_wheels(tmp_path / "database-wheels"), {**manifest(), "database": {}})
    files.update({f"database/migrations/{name}": content for name, content in DATABASE_MIGRATIONS.items()})
    return write_package(tmp_path / "weather-database.esplugin", files).read_bytes()


@pytest.fixture
def database_node(node, database_package_bytes):
    reconciler, django, launcher, venv_builder, desired = node
    django.packages[12] = database_package_bytes
    django.database_passwords[7] = APP_PASSWORD

    def with_database(**overrides):
        database = database_section(**overrides.pop("database", {}))
        return desired(database_package_bytes, database=database, **overrides)

    return reconciler, django, launcher, desired, with_database


async def test_a_database_is_provisioned_after_the_credentials_and_before_the_proxy_password_runtime_file_and_spawn(
    database_node, monkeypatch
):
    reconciler, django, launcher, desired, with_database = database_node
    real_fetch = DjangoNodeClient.fetch_runtime_credentials

    async def noting_fetch(client, placement_id):
        launcher.operations.append(("fetch_credentials", placement_id))
        return await real_fetch(client, placement_id)

    monkeypatch.setattr(DjangoNodeClient, "fetch_runtime_credentials", noting_fetch)

    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    steps = [operation[0] for operation in launcher.operations]
    start = steps.index("fetch_credentials")
    assert [step for step in steps[start:] if step not in ("prepare_plugin", "prune_code")][:5] == [
        "fetch_credentials",
        "provision",
        "issue_password",
        "write_runtime_file",
        "spawn",
    ]
    [call] = desired.provisioner.calls
    assert call["plugin"] == "weather"
    assert call["app_password"] == APP_PASSWORD
    assert call["desired"] == with_database().placements[0].database
    assert sorted((migration.name, migration.content) for migration in call["migrations"]) == sorted(
        DATABASE_MIGRATIONS.items()
    )
    environment = launcher.spawned[0]["environment"]
    assert environment["DATABASE_URL"] == (
        f"postgresql://weather_app:{APP_PASSWORD}@plugins_db:5432/plugin_weather?application_name=weather"
    )
    assert environment["EPICSTAFF_PLUGIN_DB_CONNECTIONS"] == "3"
    report = reconciler.reports()[0].database
    assert (report.state, report.applied_migrations, report.size_bytes, report.last_error) == (
        "ready",
        ["001_places.sql", "002_more.sql"],
        8192,
        None,
    )
    assert report.installation_id == "0123456789abcdef0123456789abcdef"
    # The app password is a secret: never in the runtime file, a report or a log line.
    assert APP_PASSWORD.encode() not in launcher.runtime_files["weather"]
    assert not [reports for reports in desired.changes if APP_PASSWORD in str([item.model_dump_json() for item in reports])]


async def test_a_failed_provisioning_starts_nothing_and_a_restart_tries_again(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    message = 'plugins_db already has role "weather_owner" that this plugin installation did not create'
    desired.provisioner.failures.append(DatabaseProvisioningError("conflict", message))

    await reconciler.apply(with_database())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")

    report = reconciler.reports()[0]
    assert report.last_error == message
    assert (report.database.state, report.database.last_error) == ("failed", message)
    assert launcher.spawned == []
    assert listed_passwords(layout_of(desired)) == []

    await reconciler.apply(with_database(restart_generation=1))
    await wait_until(lambda: running(reconciler))

    assert len(desired.provisioner.calls) == 2
    assert reconciler.reports()[0].database.state == "ready"
    assert reconciler.reports()[0].last_error is None


async def test_an_unreachable_plugins_db_is_reported_and_retried(database_node, monkeypatch):
    monkeypatch.setattr(reconciler_module, "TRANSIENT_RETRY_SECONDS", 0.3)
    reconciler, django, launcher, desired, with_database = database_node
    desired.provisioner.failures.append(DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached: refused"))

    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    reports_during = [
        reports[0].database
        for reports in desired.changes
        if reports and reports[0].database is not None and reports[0].database.last_error
    ]
    assert reports_during and reports_during[0].state == "provisioning"
    assert "cannot be reached" in reports_during[0].last_error
    assert len(desired.provisioner.calls) == 2
    assert len(launcher.spawned) == 1


async def test_a_changed_database_section_is_provisioned_again_and_restarts_the_process(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    await reconciler.apply(with_database(database={"connection_limit": 2}))
    await wait_until(lambda: len(launcher.spawned) == 2)
    await wait_until(lambda: running(reconciler))

    assert [call["desired"].connection_limit for call in desired.provisioner.calls] == [3, 2]
    assert launcher.spawned[1]["environment"]["EPICSTAFF_PLUGIN_DB_CONNECTIONS"] == "2"


async def test_a_restart_of_an_unchanged_database_does_not_provision_it_again(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    await reconciler.apply(with_database(restart_generation=1))
    await wait_until(lambda: len(launcher.spawned) == 2)

    assert len(desired.provisioner.calls) == 1


async def backed_up(reconciler, desired, upgrade_ids):
    """Backups of the running placement's database, as the node takes them before upgrades."""
    from es_plugins.database.backup_service import BackupRequest

    database = reconciler.controllers()[0].desired.database
    return [
        await desired.backups.backup(
            BackupRequest(plugin="weather", database=database, upgrade_id=upgrade_id, reason="pre_upgrade", version="0.2.0")
        )
        for upgrade_id in upgrade_ids
    ]


async def test_the_disk_a_placement_uses_outside_its_home_is_its_database_and_its_backups(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    stored = await backed_up(reconciler, desired, [5, 6])

    [controller] = reconciler.controllers()

    assert controller.bytes_outside_home() == 8192 + sum(backup.metadata.size_bytes for backup in stored)


def _unreportable(monkeypatch, file_name):
    """The report cannot carry the backup `file_name`, as when its metadata and the contract differ."""
    from es_plugins.database.backup_store import StoredBackup
    from src.shared.models.plugin_nodes import BackupFileReport

    real_report = StoredBackup.report

    def report(backup):
        if backup.file_name == file_name:
            BackupFileReport.model_validate({**real_report(backup).model_dump(), "version": ""})
        return real_report(backup)

    monkeypatch.setattr(StoredBackup, "report", report)


async def test_a_backup_that_cannot_be_reported_is_set_aside_and_the_inventory_stays_whole(database_node, monkeypatch):
    from es_plugins.database.backup_store import QUARANTINE_SUFFIX

    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    reportable, unreportable = await backed_up(reconciler, desired, [5, 6])
    assert [backup.file_name for backup in reconciler.reports()[0].backups] == [unreportable.file_name, reportable.file_name]
    _unreportable(monkeypatch, unreportable.file_name)
    log_lines = []
    sink = logger.add(log_lines.append, format="{message}", level="WARNING")
    try:
        [report] = reconciler.reports()
    finally:
        logger.remove(sink)

    # EpicStaff marks it deleted: its file is no longer a backup on the node.
    assert [backup.file_name for backup in report.backups] == [reportable.file_name]
    quarantined = unreportable.file_name + QUARANTINE_SUFFIX
    assert report.last_error == (
        f"Backup {unreportable.file_name} could not be reported to EpicStaff (version: String should have at "
        f"least 1 character), so the node set it aside as {quarantined}; EpicStaff no longer lists it."
    )
    assert not unreportable.path.exists()
    assert unreportable.path.with_name(quarantined).exists()
    assert any("plugins.backup.quarantined" in line and quarantined in line for line in log_lines)
    # The next report is whole too, and the process runs on.
    [again] = reconciler.reports()
    assert [backup.file_name for backup in again.backups] == [reportable.file_name]
    assert running(reconciler)


async def test_a_backup_that_cannot_be_reported_nor_set_aside_withholds_the_inventory(database_node, monkeypatch):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    reportable, unreportable = await backed_up(reconciler, desired, [5, 6])
    _unreportable(monkeypatch, unreportable.file_name)

    def refuse(plugin, file_name):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(desired.services.backup_store, "quarantine", refuse)

    # A whole inventory without it would have EpicStaff mark it deleted while its file stays.
    assert reconciler.reports()[0].backups is None
    assert unreportable.path.exists()


async def test_a_changed_host_list_rewrites_the_policy_without_a_restart(node, layout):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    hosts_file = layout.egress_policy_directory / HOSTS_FILE_NAME
    assert json.loads(hosts_file.read_text()) == {"weather": []}

    await reconciler.apply(desired(egress={"hosts": ["geocoding-api.open-meteo.com"]}))
    await asyncio.sleep(0.5)

    assert json.loads(hosts_file.read_text()) == {"weather": ["geocoding-api.open-meteo.com"]}
    assert len(launcher.spawned) == 1


async def test_the_proxy_password_is_kept_across_restarts_and_removed_once_stopped_for_good(node, layout):
    reconciler, django, launcher, _, desired = node
    await reconciler.apply(desired())
    await wait_until(lambda: running(reconciler))
    first = proxy_password(layout, launcher.spawned[0])

    await reconciler.apply(desired(restart_generation=1))
    await wait_until(lambda: len(launcher.spawned) == 2)
    assert proxy_password(layout, launcher.spawned[1]) == first

    await reconciler.apply(desired(restart_generation=1, desired_state="stopped"))
    await wait_until(lambda: reconciler.reports()[0].observed_state == "stopped")
    assert listed_passwords(layout) == []

    await reconciler.apply(desired(restart_generation=1))
    await wait_until(lambda: len(launcher.spawned) == 3)
    assert proxy_password(layout, launcher.spawned[2]) != first

    await reconciler.apply(desired_state([]))
    assert listed_passwords(layout) == []


async def test_permissions_changed_outside_epicstaff_stop_and_fail_the_plugin_until_a_restart(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    [controller] = reconciler.watched_databases()
    error = "database permissions changed outside EpicStaff: unexpected membership"

    await controller.fail_database(error)

    report = reconciler.reports()[0]
    assert (report.observed_state, report.last_error) == ("failed", error)
    assert (report.database.state, report.database.last_error) == ("failed", error)
    assert launcher.processes_of(UID)[0].poll() is not None
    assert listed_passwords(layout_of(desired)) == []
    assert not reconciler.watched_databases()[0].database.ready

    await reconciler.apply(with_database(restart_generation=1))
    await wait_until(lambda: running(reconciler))

    assert len(desired.provisioner.calls) == 2


def layout_of(desired):
    return desired.services.layout


def credential_fetches(django) -> int:
    return len([request for request in django.requests if request.url.path.endswith("/runtime-credentials/")])


async def test_retries_after_transient_failures_reuse_the_credentials_they_fetched(database_node, monkeypatch):
    monkeypatch.setattr(reconciler_module, "TRANSIENT_RETRY_SECONDS", 0.2)
    reconciler, django, launcher, desired, with_database = database_node
    desired.provisioner.failures.extend(
        DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached: refused") for _ in range(3)
    )

    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    assert len(desired.provisioner.calls) == 4
    assert credential_fetches(django) == 1


async def test_credentials_older_than_the_reuse_window_are_fetched_again(database_node, monkeypatch):
    monkeypatch.setattr(reconciler_module, "TRANSIENT_RETRY_SECONDS", 0.2)
    monkeypatch.setattr(reconciler_module, "CREDENTIALS_REUSE_SECONDS", 0.0)
    reconciler, django, launcher, desired, with_database = database_node
    desired.provisioner.failures.extend(
        DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached: refused") for _ in range(3)
    )

    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    assert credential_fetches(django) == 4


async def test_a_placement_that_changes_during_an_outage_gets_fresh_credentials(database_node, monkeypatch):
    monkeypatch.setattr(reconciler_module, "TRANSIENT_RETRY_SECONDS", 0.2)
    reconciler, django, launcher, desired, with_database = database_node
    desired.provisioner.failures.extend(
        DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached: refused") for _ in range(2)
    )
    await reconciler.apply(with_database())
    await wait_until(lambda: len(desired.provisioner.calls) == 1)
    django.credentials_revisions[7] = "d" * 64

    await reconciler.apply(with_database(credentials_revision="d" * 64))
    await wait_until(lambda: running(reconciler))

    assert credential_fetches(django) == 2
    assert reconciler.reports()[0].applied_credentials_revision == "d" * 64


def hosts_of(layout) -> dict:
    return json.loads((layout.egress_policy_directory / HOSTS_FILE_NAME).read_text())


async def test_a_removal_runs_once_the_controller_has_stopped_the_process(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    [process] = launcher.processes_of(UID)

    await reconciler.apply(
        desired_state(
            [], removals=[removal(uid=UID, port=desired.port, database=database_section())]
        )
    )
    await wait_until(lambda: [report.state for report in reconciler.removal_reports()] == ["removed"])

    steps = [operation[0] for operation in launcher.operations]
    assert process.poll() is not None
    assert steps.index("drop") < steps.index("remove_plugin")
    assert ("remove_plugin", "weather", UID) in launcher.operations
    assert reconciler.reports() == []
    assert listed_passwords(layout_of(desired)) == []
    assert hosts_of(layout_of(desired)) == {}
    assert not layout_of(desired).plugin_logs("weather").exists()


async def test_a_placement_the_watchdog_fails_while_it_starts_never_runs(database_node, monkeypatch):
    reconciler, django, launcher, desired, with_database = database_node
    real_start = ProcessSupervisor.start
    error = "database permissions changed outside EpicStaff: unexpected membership"

    async def start_while_the_watchdog_fails_it(supervisor, spec):
        [controller] = reconciler.watched_databases()
        # The watchdog's failure takes the supervisor first; this start then waits for it.
        failing = asyncio.create_task(controller.fail_database(error))
        await asyncio.sleep(0)
        await real_start(supervisor, spec)
        await failing

    monkeypatch.setattr(ProcessSupervisor, "start", start_while_the_watchdog_fails_it)
    await reconciler.apply(with_database())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")
    await asyncio.sleep(0.5)

    report = reconciler.reports()[0]
    assert (report.observed_state, report.last_error) == ("failed", error)
    assert all(process.poll() is not None for process in launcher.processes_of(UID))
    assert listed_passwords(layout_of(desired)) == []


async def test_a_start_the_watchdog_fails_before_the_password_leaves_no_password(database_node, monkeypatch):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))
    real_fetch = DjangoNodeClient.fetch_runtime_credentials
    error = "database permissions changed outside EpicStaff: unexpected membership"

    async def fetch_while_the_watchdog_fails_it(client, placement_id):
        [controller] = reconciler.watched_databases()
        await controller.fail_database(error)
        return await real_fetch(client, placement_id)

    monkeypatch.setattr(DjangoNodeClient, "fetch_runtime_credentials", fetch_while_the_watchdog_fails_it)
    await reconciler.apply(with_database(restart_generation=1))
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")
    await asyncio.sleep(0.5)

    assert reconciler.reports()[0].last_error == error
    assert listed_passwords(layout_of(desired)) == []
    assert all(process.poll() is not None for process in launcher.processes_of(UID))


async def test_the_report_carries_the_ledger_with_each_files_digest(database_node):
    reconciler, django, launcher, desired, with_database = database_node

    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    ledger = reconciler.reports()[0].database.ledger
    assert [(entry.name, entry.sha256) for entry in ledger] == [
        (name, hashlib.sha256(content).hexdigest()) for name, content in sorted(DATABASE_MIGRATIONS.items())
    ]


async def test_a_failed_migration_run_reports_the_ledger_it_left(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    failure = DatabaseProvisioningError("migration", "002_more.sql line 1: [22012] division by zero")
    failure.ledger = (LedgerEntry(name="001_places.sql", sha256="a" * 64),)
    desired.provisioner.failures.append(failure)

    await reconciler.apply(with_database())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")

    report = reconciler.reports()[0].database
    assert report.state == "failed"
    assert [entry.name for entry in report.ledger] == ["001_places.sql"]
    assert report.last_error == "002_more.sql line 1: [22012] division by zero"


async def test_a_ledger_not_read_in_this_agents_life_is_reported_as_unknown(database_node):
    reconciler, django, launcher, desired, with_database = database_node
    desired.provisioner.failures.append(DatabaseProvisioningError("conflict", "roles of another installation"))

    await reconciler.apply(with_database())
    await wait_until(lambda: reconciler.reports()[0].observed_state == "failed")

    assert reconciler.reports()[0].database.ledger is None


async def test_a_placement_whose_report_cannot_be_built_is_reported_as_unknown(database_node, monkeypatch):
    reconciler, django, launcher, desired, with_database = database_node
    await reconciler.apply(with_database())
    await wait_until(lambda: running(reconciler))

    def broken(database):
        raise ValueError("not a report")

    monkeypatch.setattr(reconciler_module.PlacementDatabase, "report", broken)
    lines = []
    sink = logger.add(lines.append, format="{message}", level="ERROR")
    try:
        first = reconciler.reports()
        second = reconciler.reports()
    finally:
        logger.remove(sink)

    for reports in (first, second):
        [report] = reports
        assert (report.placement_id, report.observed_state, report.health) == (7, "unknown", "unknown")
        assert "see the node's log" in report.last_error
    assert len([line for line in lines if "could not be built" in line]) == 1
