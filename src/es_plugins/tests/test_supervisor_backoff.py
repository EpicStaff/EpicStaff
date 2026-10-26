import asyncio
import io
import signal
import time

import httpx
import pytest

from es_plugins.health.health_checker import HealthChecker
from es_plugins.logs.log_collector import LogCollector, RotatingLogFile
from es_plugins.supervisor import process_supervisor
from es_plugins.supervisor.process_supervisor import ProcessSpec, ProcessSupervisor
from es_plugins.supervisor.restart_policy import FAILURE_RESTARTS, RestartPolicy
from tests.helpers import FakeLauncher, free_port, listening_socket

UID = 20001


def test_a_process_that_crashes_at_once_backs_off_then_fails():
    policy = RestartPolicy()
    delays = []
    while (delay := policy.next_delay()) is not None:
        delays.append(delay)

    assert delays == [1, 2, 4, 8, 16, 32, 64, 128, 256, 300]
    assert policy.restarts == 10


def test_ten_restarts_in_a_row_fail_however_slowly_they_come():
    # The rule counts restarts without a stable run between them, not restarts per minute:
    # nothing here is timed, so a plugin that crashes every 5 minutes fails as surely as one
    # that crashes at once.
    policy = RestartPolicy()
    for _ in range(FAILURE_RESTARTS):
        assert policy.next_delay() is not None

    assert policy.next_delay() is None


def test_a_stable_run_starts_the_count_over():
    policy = RestartPolicy()
    for _ in range(FAILURE_RESTARTS - 1):
        policy.next_delay()

    policy.mark_stable()
    delays = [policy.next_delay() for _ in range(FAILURE_RESTARTS)]

    assert delays[:3] == [1, 2, 4]
    assert None not in delays
    assert policy.next_delay() is None
    assert policy.restarts == 2 * FAILURE_RESTARTS - 1


def test_a_plugin_that_runs_stably_between_crashes_never_fails():
    policy = RestartPolicy()

    for _ in range(3 * FAILURE_RESTARTS):
        assert policy.next_delay() == 1
        policy.mark_stable()

    assert policy.restarts == 3 * FAILURE_RESTARTS


def test_a_deliberate_start_forgets_earlier_restarts():
    policy = RestartPolicy()
    for _ in range(FAILURE_RESTARTS):
        policy.next_delay()

    policy.reset()

    assert policy.restarts == 0
    assert policy.next_delay() == 1


def spec(port: int, memory_mb: int = 256) -> ProcessSpec:
    return ProcessSpec(
        plugin="weather",
        uid=UID,
        version="0.2.0",
        argv=["/var/lib/es_plugins/venvs/weather/0.2.0/bin/python", "-I", "-m", "epicstaff_plugin.serve"],
        environment={"PORT": str(port)},
        nice=0,
        port=port,
        memory_mb=memory_mb,
    )


@pytest.fixture
def held_port():
    """A port with its listening socket held, as the agent holds it for a placement."""
    port = free_port()
    listener = listening_socket(port)
    yield port, listener.fileno()
    listener.close()


def make_supervisor(tmp_path, launcher, health_checker, listen_fd, policy=None):
    return ProcessSupervisor(
        "weather",
        UID,
        launcher,
        health_checker,
        LogCollector("weather", RotatingLogFile(tmp_path / "logs"), io.StringIO()),
        lambda: None,
        listen_fd=listen_fd,
        policy=policy or RestartPolicy(initial_delay=0.05),
    )


@pytest.fixture
async def supervised(tmp_path, held_port):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(tmp_path, launcher, health_checker, listen_fd)
    yield supervisor, launcher, port
    await supervisor.stop()
    launcher.stop_all()
    await health_checker.aclose()


async def wait_until(condition, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


@pytest.mark.linux
async def test_a_started_process_is_running_once_its_health_check_answers(supervised):
    supervisor, launcher, port = supervised

    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    status = supervisor.status()
    assert (status.health, status.restarts, status.version) == ("ok", 0, "0.2.0")
    assert status.pid is not None


@pytest.mark.linux
async def test_a_crashed_process_is_restarted_after_the_backoff(supervised):
    supervisor, launcher, port = supervised
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    launcher.kill_running(UID, signal.SIGKILL)
    await wait_until(lambda: len(launcher.spawned) == 2)
    await wait_until(lambda: supervisor.status().observed_state == "running")

    status = supervisor.status()
    assert status.restarts == 1
    assert status.last_error == "its process was killed by SIGKILL"
    assert ("kill_uid", UID) in launcher.operations


@pytest.mark.linux
async def test_a_deliberate_stop_terminates_and_does_not_restart(supervised):
    supervisor, launcher, port = supervised
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    await supervisor.stop()
    await asyncio.sleep(0.3)

    assert supervisor.status().observed_state == "stopped"
    assert len(launcher.spawned) == 1
    assert ("terminate_uid", UID) in launcher.operations
    # It exited on SIGTERM by itself: the SIGKILL after it found nothing left to kill.
    assert [process.returncode for process in launcher.processes_of(UID)] == [0]


@pytest.mark.linux
async def test_a_deliberate_stop_gives_a_process_that_ignores_sigterm_the_grace_period(
    tmp_path, monkeypatch, held_port
):
    monkeypatch.setattr(process_supervisor, "STOP_GRACE_SECONDS", 1.0)
    launcher = FakeLauncher()
    launcher.ignore_sigterm = True
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(tmp_path, launcher, health_checker, listen_fd)
    try:
        await supervisor.start(spec(port))
        await wait_until(lambda: supervisor.status().observed_state == "running")

        started = time.monotonic()
        await supervisor.stop()
        elapsed = time.monotonic() - started

        assert elapsed >= 1.0
        signals = [operation for operation in launcher.operations if operation[1:] == (UID,)]
        assert signals == [("terminate_uid", UID), ("kill_uid", UID)]
        assert [process.returncode for process in launcher.processes_of(UID)] == [-signal.SIGKILL]
    finally:
        launcher.stop_all()
        await health_checker.aclose()


@pytest.mark.linux
async def test_a_stop_during_the_backoff_ends_it_at_once_without_a_new_process(
    tmp_path, held_port
):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(
        tmp_path, launcher, health_checker, listen_fd, RestartPolicy(initial_delay=60)
    )
    try:
        await supervisor.start(spec(port))
        await wait_until(lambda: supervisor.status().observed_state == "running")
        launcher.kill_running(UID)
        await wait_until(lambda: supervisor.status().restarts == 1)

        started = time.monotonic()
        await supervisor.stop()

        assert time.monotonic() - started < 2.0
        assert supervisor.status().observed_state == "stopped"
        assert len(launcher.spawned) == 1
    finally:
        launcher.stop_all()
        await health_checker.aclose()


@pytest.mark.linux
async def test_a_process_that_never_answers_its_health_check_is_restarted(
    tmp_path, monkeypatch, held_port
):
    monkeypatch.setattr(process_supervisor, "STARTUP_GRACE_SECONDS", 0.5)
    launcher = FakeLauncher()
    unhealthy = HealthChecker(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    port, listen_fd = held_port
    supervisor = make_supervisor(tmp_path, launcher, unhealthy, listen_fd)
    try:
        await supervisor.start(spec(port))
        await wait_until(lambda: len(launcher.spawned) >= 2)

        assert "did not answer its health check" in supervisor.status().last_error
    finally:
        await supervisor.stop()
        launcher.stop_all()
        await unhealthy.aclose()


@pytest.mark.linux
async def test_too_many_restarts_leave_the_plugin_failed(tmp_path, held_port):
    launcher = FakeLauncher()
    launcher.refuse_spawn = "spawn: PermissionError: [Errno 1] Operation not permitted"
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(
        tmp_path,
        launcher,
        health_checker,
        listen_fd,
        RestartPolicy(initial_delay=0.001, maximum_delay=0.001),
    )
    try:
        await supervisor.start(spec(port))
        await wait_until(lambda: supervisor.failed)

        status = supervisor.status()
        assert status.restarts == 10
        assert "could not be started" in status.last_error
    finally:
        await supervisor.stop()
        await health_checker.aclose()


@pytest.mark.linux
async def test_stable_runs_between_crashes_keep_the_plugin_from_failing(
    tmp_path, monkeypatch, held_port
):
    monkeypatch.setattr(process_supervisor, "STABLE_AFTER_SECONDS", 0.0)
    monkeypatch.setattr(process_supervisor, "STARTUP_PROBE_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(process_supervisor, "HEALTH_INTERVAL_SECONDS", 0.05)
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(
        tmp_path,
        launcher,
        health_checker,
        listen_fd,
        RestartPolicy(initial_delay=0.05, failure_restarts=2),
    )
    try:
        await supervisor.start(spec(port))
        for crash in range(1, 5):
            await wait_until(lambda: supervisor.status().observed_state == "running")
            # A few healthy answers after the first: the run counts as stable.
            await asyncio.sleep(0.3)
            launcher.kill_running(UID)
            await wait_until(lambda crash=crash: len(launcher.spawned) == crash + 1)

        await wait_until(lambda: supervisor.status().observed_state == "running")
        assert not supervisor.failed
        assert supervisor.status().restarts == 4
    finally:
        await supervisor.stop()
        launcher.stop_all()
        await health_checker.aclose()


@pytest.mark.linux
async def test_crashes_without_a_stable_run_between_them_leave_the_plugin_failed(
    tmp_path, monkeypatch, held_port
):
    monkeypatch.setattr(process_supervisor, "STARTUP_PROBE_INTERVAL_SECONDS", 0.05)
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(
        tmp_path,
        launcher,
        health_checker,
        listen_fd,
        RestartPolicy(initial_delay=0.05, failure_restarts=2),
    )
    try:
        await supervisor.start(spec(port))
        for crash in range(1, 4):
            await wait_until(lambda: supervisor.status().observed_state == "running")
            launcher.kill_running(UID)
            await wait_until(
                lambda crash=crash: supervisor.failed or len(launcher.spawned) == crash + 1
            )

        await wait_until(lambda: supervisor.failed)
        status = supervisor.status()
        assert (status.restarts, len(launcher.spawned)) == (2, 3)
        assert status.last_error == "its process was killed by SIGKILL"
        assert status.rss_mb is None
    finally:
        await supervisor.stop()
        launcher.stop_all()
        await health_checker.aclose()


@pytest.mark.linux
async def test_a_process_is_not_started_without_its_held_listening_socket(tmp_path):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    supervisor = make_supervisor(
        tmp_path,
        launcher,
        health_checker,
        None,
        RestartPolicy(initial_delay=0.001, maximum_delay=0.001),
    )
    try:
        await supervisor.start(spec(free_port()))
        await wait_until(lambda: supervisor.failed)

        assert supervisor.status().last_error == "its listening socket was not bound"
        assert launcher.spawned == []
    finally:
        await supervisor.stop()
        await health_checker.aclose()


@pytest.mark.linux
async def test_an_error_of_the_agent_itself_is_one_more_restart(supervised):
    supervisor, launcher, port = supervised
    real_spawn = launcher.spawn
    calls = []

    async def spawn_failing_once(*arguments):
        calls.append(arguments)
        if len(calls) == 1:
            raise RuntimeError("unexpected")
        return await real_spawn(*arguments)

    launcher.spawn = spawn_failing_once
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    status = supervisor.status()
    assert status.restarts == 1
    assert status.last_error == "internal error of the node agent: unexpected"


@pytest.mark.linux
async def test_a_plugin_failed_for_its_disk_is_killed_and_not_restarted(supervised):
    supervisor, launcher, port = supervised
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    supervisor.fail_for("uses 70 MB of disk, more than its limit of 64 MB")
    await wait_until(lambda: supervisor.failed)
    await asyncio.sleep(0.5)

    status = supervisor.status()
    assert status.last_error == "uses 70 MB of disk, more than its limit of 64 MB"
    assert (status.pid, status.rss_mb, status.restarts) == (None, None, 0)
    assert len(launcher.spawned) == 1
    assert ("kill_uid", UID) in launcher.operations
    assert ("terminate_uid", UID) not in launcher.operations
    assert [process.returncode for process in launcher.processes_of(UID)] == [-signal.SIGKILL]


@pytest.mark.linux
async def test_a_plugin_failed_for_its_disk_during_a_backoff_is_not_started_again(
    tmp_path, held_port
):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port, listen_fd = held_port
    supervisor = make_supervisor(
        tmp_path, launcher, health_checker, listen_fd, RestartPolicy(initial_delay=60)
    )
    try:
        await supervisor.start(spec(port))
        await wait_until(lambda: supervisor.status().observed_state == "running")
        launcher.kill_running(UID)
        await wait_until(lambda: supervisor.status().restarts == 1)

        supervisor.fail_for("has 1001 files, more than its limit of 1000 files")
        await wait_until(lambda: supervisor.failed, timeout=2)

        assert supervisor.status().last_error == "has 1001 files, more than its limit of 1000 files"
        assert len(launcher.spawned) == 1
    finally:
        await supervisor.stop()
        launcher.stop_all()
        await health_checker.aclose()


@pytest.mark.linux
async def test_a_deliberate_start_after_a_disk_failure_runs_the_plugin_again(supervised):
    supervisor, launcher, port = supervised
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")
    supervisor.fail_for("uses 70 MB of disk, more than its limit of 64 MB")
    await wait_until(lambda: supervisor.failed)

    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")

    assert supervisor.status().last_error is None
    assert len(launcher.spawned) == 2
