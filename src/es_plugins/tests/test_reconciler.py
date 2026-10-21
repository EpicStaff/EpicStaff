"""The reconciler against django_app (`httpx.MockTransport`) and the launcher stand-in.

The plugin's process is a real child answering the health check; the venv build is
recorded instead of run (it has its own tests).
"""

import asyncio
import base64
import errno
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from es_plugins.agent import reconciler as reconciler_module
from es_plugins.agent.django_client import DjangoNodeClient
from es_plugins.agent.main import prepare_agent_directories
from es_plugins.agent.port_reservation import PortReservation
from es_plugins.agent.reconciler import AgentServices, Reconciler
from es_plugins.health.health_checker import HealthChecker
from es_plugins.hooks.hook_caller import PluginHookCaller
from es_plugins.hooks.hook_runner import RESTARTED_DURING_HOOK, STOPPED_DURING_HOOK
from es_plugins.node_disk import INSTALL_RESERVE_BYTES, NodeDisk
from es_plugins.packages.package_fetcher import PackageFetcher
from tests.helpers import (
    API_URL,
    HOOK_ASSERTION,
    NODE_KEY,
    SERVICE_ACCOUNT_KEY,
    FakeDjango,
    FakeLauncher,
    backend_wheels,
    desired_state,
    free_port,
    free_ports,
    hook_body,
    hook_invocation,
    hook_job,
    manifest,
    package_files,
    placement,
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
    venv_builder = RecordingVenvBuilder()
    health_checker = HealthChecker()
    hook_caller = PluginHookCaller()
    changes = []
    port, other_port = free_ports(2)
    volume = Volume()
    ports = PortReservation([port, other_port])
    ports.reserve()
    services = AgentServices(
        layout=layout,
        django=client,
        fetcher=PackageFetcher(client, layout.downloads_directory),
        launcher=launcher,
        health_checker=health_checker,
        ports=ports,
        disk=NodeDisk(layout.data_root, statvfs=volume),
        hook_caller=hook_caller,
        on_change=lambda: changes.append(reconciler.reports()),
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
    yield reconciler, django, launcher, venv_builder, desired
    await reconciler.close()
    ports.close()
    launcher.stop_all()
    await health_checker.aclose()
    await hook_caller.aclose()
    await client.aclose()


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
    }
    assert not any("secret" in argument for argument in spawned["argv"])
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
