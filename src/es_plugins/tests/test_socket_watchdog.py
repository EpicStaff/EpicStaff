"""The socket watchdog: a plugin UID listening on a port of its own, or holding too many inet
sockets, is stopped and stays stopped."""

import asyncio
import io
import os

import pytest
from loguru import logger

from es_plugins.health.health_checker import HealthChecker
from es_plugins.logs.log_collector import LogCollector, RotatingLogFile
from es_plugins.supervisor import socket_watchdog
from es_plugins.supervisor.process_supervisor import ProcessSpec, ProcessSupervisor
from es_plugins.supervisor.restart_policy import RestartPolicy
from es_plugins.supervisor.socket_watchdog import (
    MAX_INET_SOCKETS,
    SocketEntry,
    SocketTables,
    SocketWatchdog,
    parse_socket_line,
)
from tests.helpers import FakeLauncher, free_port, listening_socket
from tests.test_supervisor_backoff import wait_until

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
IPV6_ANY = "0" * 32


def row(number: int, local: str, state: int, uid: int, remote: str = "00000000:0000") -> str:
    return (
        f"{number:>4}: {local} {remote} {state:02X} 00000000:00000000 00:00000000 00000000 "
        f"{uid:>5}        0 {10000 + number} 1 0000000000000000 100 0 0 10 0\n"
    )


def write_tables(root, **tables: list[str]) -> None:
    root.mkdir(exist_ok=True)
    for name in ("tcp", "tcp6", "udp", "udp6"):
        if name in tables:
            (root / name).write_text(HEADER + "".join(tables[name]))


@pytest.mark.parametrize(
    ("line", "entry"),
    [
        (row(0, "0100007F:4E21", 0x0A, 10000), SocketEntry(local_port=20001, state=0x0A, uid=10000)),
        (row(1, f"{IPV6_ANY}:BFCD", 0x0A, 20011), SocketEntry(local_port=49101, state=0x0A, uid=20011)),
        (row(2, "0100007F:A1B2", 0x01, 20012, "0100007F:0035"), SocketEntry(local_port=41394, state=0x01, uid=20012)),
    ],
)
def test_a_row_of_the_kernels_tables_is_read(line, entry):
    assert parse_socket_line(line) == entry


@pytest.mark.parametrize(
    "line",
    ["", "garbage\n", HEADER, row(3, "0100007F", 0x0A, 1), row(4, "0100007F:XYZ", 0x0A, 1), "   5: a b c d e f g h i\n"],
)
def test_a_line_that_is_not_a_row_is_skipped(line):
    assert parse_socket_line(line) is None


def test_each_uids_sockets_are_counted_across_the_four_tables_and_its_listening_port_found(tmp_path):
    root = tmp_path / "net"
    write_tables(
        root,
        tcp=[row(0, "0100007F:4E21", 0x0A, 10000), row(1, "0100007F:9C40", 0x01, 20013, "0A000002:1F90")],
        tcp6=[row(0, f"{IPV6_ANY}:BFCD", 0x0A, 20011)],
        udp=[row(index, f"0100007F:{0x6000 + index:04X}", 0x01, 20012) for index in range(5)],
        udp6=[row(0, f"{IPV6_ANY}:6100", 0x07, 20012)],
    )

    use = SocketTables(root).use_of({20011, 20012, 20013})

    assert use.listening == {20011: 49101}
    assert dict(use.sockets) == {20011: 1, 20012: 6, 20013: 1}


def test_a_table_is_read_no_further_than_its_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(socket_watchdog, "MAX_LINES_PER_TABLE", 3)
    root = tmp_path / "net"
    write_tables(root, udp=[row(index, f"0100007F:{0x6000 + index:04X}", 0x01, 20012) for index in range(10)])

    assert SocketTables(root).use_of({20012}).sockets[20012] == 3


def test_a_table_that_cannot_be_read_is_logged_once_and_left_out(tmp_path):
    root = tmp_path / "net"
    write_tables(root, tcp=[row(0, "0100007F:9C40", 0x01, 20013, "0A000002:1F90")])
    tables = SocketTables(root)
    lines = []
    sink = logger.add(lines.append, format="{message}", level="WARNING")
    try:
        first = tables.use_of({20013})
        second = tables.use_of({20013})
    finally:
        logger.remove(sink)

    assert first.sockets[20013] == second.sockets[20013] == 1
    assert sorted(line.split(":")[0] for line in lines) == [
        f"The socket watchdog cannot read {name}" for name in ("tcp6", "udp", "udp6")
    ]


@pytest.fixture
async def watched(tmp_path):
    launcher = FakeLauncher()
    health_checker = HealthChecker()
    port = free_port()
    listener = listening_socket(port)
    supervisor = ProcessSupervisor(
        "weather",
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


def spec(port: int) -> ProcessSpec:
    return ProcessSpec(
        plugin="weather",
        uid=os.getuid(),
        version="0.2.0",
        argv=["python"],
        environment={"PORT": str(port)},
        nice=0,
        port=port,
        memory_mb=1_000_000,
    )


async def _running(supervisor, port):
    await supervisor.start(spec(port))
    await wait_until(lambda: supervisor.status().observed_state == "running")


@pytest.mark.linux
@pytest.mark.parametrize(
    ("tables", "reason"),
    [
        ({"tcp6": [row(0, f"{IPV6_ANY}:BFCD", 0x0A, os.getuid())]}, "it listened on TCP port 49101 of its own"),
        (
            {"udp": [row(index, "0100007F:6000", 0x01, os.getuid(), "0A000002:0035") for index in range(MAX_INET_SOCKETS + 1)]},
            f"it held {MAX_INET_SOCKETS + 1} network sockets, more than the {MAX_INET_SOCKETS} a plugin may",
        ),
    ],
)
async def test_a_breach_kills_the_uid_and_leaves_the_plugin_failed_without_a_restart(watched, tmp_path, tables, reason):
    supervisor, launcher, port = watched
    await _running(supervisor, port)
    write_tables(tmp_path / "net", **tables)
    watchdog = SocketWatchdog(lambda: [supervisor], tables=SocketTables(tmp_path / "net"))

    stopped = await watchdog.check_once()
    await wait_until(lambda: supervisor.status().observed_state == "failed")
    await asyncio.sleep(0.3)

    assert stopped == [supervisor]
    assert ("kill_uid", os.getuid()) in launcher.operations
    status = supervisor.status()
    assert status.last_error.startswith(reason)
    assert status.last_error.endswith("it stays stopped until it is restarted")
    assert (status.observed_state, len(launcher.spawned)) == ("failed", 1)


@pytest.mark.linux
async def test_a_plugin_within_the_rules_keeps_running(watched, tmp_path):
    supervisor, launcher, port = watched
    await _running(supervisor, port)
    write_tables(
        tmp_path / "net",
        tcp=[row(0, "0100007F:4E21", 0x0A, 10000), row(1, "0100007F:9C40", 0x01, os.getuid(), "0A000002:1F90")],
        udp=[row(index, "0100007F:6000", 0x01, os.getuid()) for index in range(MAX_INET_SOCKETS - 1)],
    )
    watchdog = SocketWatchdog(lambda: [supervisor], tables=SocketTables(tmp_path / "net"))

    assert await watchdog.check_once() == []

    assert supervisor.status().observed_state == "running"


async def test_a_check_that_fails_does_not_end_the_watchdog():
    class Running:
        uid = 20011
        plugin = "weather"
        watching = True

    class Failing(SocketTables):
        calls = 0

        def use_of(self, uids):
            Failing.calls += 1
            raise RuntimeError("unexpected")

    watchdog = SocketWatchdog(lambda: [Running()], tables=Failing(), interval=0.01)
    task = asyncio.create_task(watchdog.run())
    try:
        await wait_until(lambda: Failing.calls >= 3)
        assert not task.done()
    finally:
        task.cancel()
