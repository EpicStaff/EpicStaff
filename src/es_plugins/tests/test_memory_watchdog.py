import io
import os

import pytest

from es_plugins.health.health_checker import HealthChecker
from es_plugins.logs.log_collector import LogCollector, RotatingLogFile
from es_plugins.process_table import ProcessTable
from es_plugins.supervisor.memory_watchdog import MemoryWatchdog
from es_plugins.supervisor.process_supervisor import ProcessSpec, ProcessSupervisor
from es_plugins.supervisor.restart_policy import RestartPolicy
from tests.helpers import FakeLauncher, free_port, listening_socket
from tests.test_supervisor_backoff import wait_until


def write_status(proc_root, pid, uid, rss_kib=None, state="S (sleeping)", file_kib=30_000):
    directory = proc_root / str(pid)
    directory.mkdir(parents=True)
    lines = ["Name:\tpython", f"State:\t{state}", f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}"]
    if rss_kib is not None:
        anonymous, shared = rss_kib - rss_kib // 10, rss_kib // 10
        lines += [
            f"VmRSS:\t{rss_kib + file_kib:>8} kB",
            f"RssAnon:\t{anonymous:>8} kB",
            f"RssFile:\t{file_kib:>8} kB",
            f"RssShmem:\t{shared:>8} kB",
        ]
    (directory / "status").write_text("\n".join(lines) + "\n")


def test_rss_is_summed_over_every_process_of_a_uid(tmp_path):
    write_status(tmp_path, 30, 20001, 9_000)
    # A forked child holding the memory, and one reparented after its parent exited.
    write_status(tmp_path, 31, 20001, 170_000)
    write_status(tmp_path, 77, 20001, 1_000)
    write_status(tmp_path, 33, 20002, 48_000)
    write_status(tmp_path, 40, 20001, state="Z (zombie)")
    (tmp_path / "self").mkdir()
    table = ProcessTable(tmp_path)

    assert table.rss_kib_by_uid([20001, 20002, 20003]) == {20001: 180_000, 20002: 48_000, 20003: 0}
    assert table.living_pids_of_uid(20001) == [30, 31, 77]


def test_the_interpreter_and_libraries_every_process_maps_are_not_counted(tmp_path):
    # Two workers of one plugin, each mapping the same 30 MB of interpreter and libraries.
    write_status(tmp_path, 30, 20001, 10_000, file_kib=30_000)
    write_status(tmp_path, 31, 20001, 10_000, file_kib=30_000)

    assert ProcessTable(tmp_path).rss_kib_by_uid([20001]) == {20001: 20_000}


def test_an_old_kernel_without_rss_anon_falls_back_to_vm_rss(tmp_path):
    directory = tmp_path / "30"
    directory.mkdir()
    (directory / "status").write_text("State:\tS\nUid:\t20001\t20001\t20001\t20001\nVmRSS:\t 5000 kB\n")

    assert ProcessTable(tmp_path).rss_kib_by_uid([20001]) == {20001: 5000}


def test_a_process_that_vanishes_while_read_is_left_out(tmp_path):
    write_status(tmp_path, 30, 20001, 1_000)
    (tmp_path / "31").mkdir()

    assert [entry.pid for entry in ProcessTable(tmp_path).read()] == [30]


@pytest.fixture
async def watched(tmp_path):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port = free_port()
    listener = listening_socket(port)
    supervisor = ProcessSupervisor(
        "weather",
        # The child runs as the test's own user: summing that UID's RSS on the real /proc
        # covers the child, the test runner and everything else the user runs.
        os.getuid(),
        launcher,
        health_checker,
        LogCollector("weather", RotatingLogFile(tmp_path / "logs"), io.StringIO()),
        lambda: None,
        listen_fd=listener.fileno(),
        policy=RestartPolicy(initial_delay=0.05),
    )
    yield supervisor, launcher, port
    await supervisor.stop()
    launcher.stop_all()
    listener.close()
    await health_checker.aclose()


def spec(memory_mb: int, port: int) -> ProcessSpec:
    return ProcessSpec(
        plugin="weather",
        uid=os.getuid(),
        version="0.2.0",
        argv=["python"],
        environment={"PORT": str(port)},
        nice=0,
        port=port,
        memory_mb=memory_mb,
    )


@pytest.mark.linux
async def test_a_plugin_over_its_cap_is_killed_by_uid_and_restarted(watched):
    supervisor, launcher, port = watched
    await supervisor.start(spec(memory_mb=1, port=port))
    await wait_until(lambda: supervisor.status().observed_state == "running")
    watchdog = MemoryWatchdog(ProcessTable(), lambda: [supervisor])

    over_cap = watchdog.check_once()
    await wait_until(lambda: len(launcher.spawned) == 2)

    assert over_cap == [supervisor]
    assert ("kill_uid", os.getuid()) in launcher.operations
    status = supervisor.status()
    assert status.restarts == 1
    assert "more than its memory limit of 1 MB" in status.last_error


@pytest.mark.linux
async def test_a_plugin_under_its_cap_keeps_running_and_its_rss_is_recorded(watched):
    supervisor, launcher, port = watched
    await supervisor.start(spec(memory_mb=1_000_000, port=port))
    await wait_until(lambda: supervisor.status().observed_state == "running")
    watchdog = MemoryWatchdog(ProcessTable(), lambda: [supervisor])

    assert watchdog.check_once() == []

    assert supervisor.status().rss_mb > 0
    assert len(launcher.spawned) == 1

