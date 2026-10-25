import asyncio
import errno
import json
import os
import resource
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from epicstaff_plugin.contracts.runtime import LISTEN_FD_ENVIRONMENT_VARIABLE
from pydantic import ValidationError

from es_plugins.agent.launcher_client import LauncherClient, LauncherError
from es_plugins.disk_usage import DiskUsage
from es_plugins.launcher import protocol
from es_plugins.launcher.directory_setup import DirectorySetup
from es_plugins.launcher.__main__ import agent_environment
from es_plugins.launcher.kill_by_uid import kill_uid, run_as_user
from es_plugins.launcher.privileged_launcher import (
    PLUGIN_OOM_SCORE_ADJ,
    PLUGIN_RESOURCE_LIMITS,
    LauncherOperations,
    LauncherRefusalError,
    LauncherServer,
    serve_until_agent_exits,
)
from es_plugins.launcher.process_spawn import LISTEN_FD, SpawnError, SpawnSpec, spawn_process
from es_plugins.process_table import ProcessTable
from es_plugins.uid_range import UidRange
from tests.helpers import SYSTEM_PYTHON, OwnProcessTable

PLUGIN_UID = 20011


def spawn_request(**overrides):
    request = {
        "operation": "spawn",
        "plugin": "weather",
        "uid": PLUGIN_UID,
        "argv": ["/var/lib/es_plugins/venvs/weather/0.2.0/bin/python", "-I", "-m", "x"],
        "environment": {"PORT": "20001"},
        "nice": 0,
        **overrides,
    }
    return protocol.decode_request(json.dumps(request).encode())


def test_the_agent_gets_both_database_passwords_and_nothing_else_of_the_launchers(layout, monkeypatch):
    monkeypatch.setenv("PLUGINS_DB_ADMIN_PASSWORD", "d" * 64)
    monkeypatch.setenv("PLUGINS_NODE_KEY", "n" * 64)
    monkeypatch.setenv("POSTGRES_PASSWORD", "s" * 64)
    monkeypatch.setenv("PLUGINS_DB_BACKUP_PASSWORD", "b" * 64)
    monkeypatch.setenv("PLUGINS_DB_SUPERUSER_PASSWORD", "u" * 64)

    environment = agent_environment(layout)

    assert (environment["PLUGINS_DB_ADMIN_PASSWORD"], environment["PLUGINS_NODE_KEY"]) == ("d" * 64, "n" * 64)
    assert environment["PLUGINS_DB_BACKUP_PASSWORD"] == "b" * 64
    assert "POSTGRES_PASSWORD" not in environment
    assert "PLUGINS_DB_SUPERUSER_PASSWORD" not in environment


def test_a_valid_request_is_decoded():
    request = spawn_request()

    assert isinstance(request, protocol.Spawn)
    assert request.argv[1] == "-I"


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected": 1},
        {"operation": "chmod"},
        {"plugin": "../other"},
        {"plugin": "Weather"},
        {"uid": 0},
        {"uid": -1},
        {"nice": -5},
        {"argv": []},
        {"argv": ["/bin/sh\0-c"]},
        {"environment": {"BAD NAME": "x"}},
        {"environment": {"TOKEN": "a\0b"}},
    ],
)
def test_an_unexpected_request_is_refused(overrides):
    with pytest.raises(ValidationError):
        spawn_request(**overrides)


@pytest.mark.parametrize("version", ["..", "0.2.0/../../x", "../0.2.0", ".hidden"])
def test_an_install_into_another_directory_is_refused(version):
    with pytest.raises(ValidationError):
        protocol.decode_request(
            json.dumps(
                {"operation": "install_code", "plugin": "weather", "uid": PLUGIN_UID, "version": version}
            ).encode()
        )


@pytest.fixture
def operations(layout, unprivileged_setup):
    return LauncherOperations(
        layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), unprivileged_setup, ProcessTable()
    )


def test_a_uid_outside_the_range_is_refused(operations):
    with pytest.raises(LauncherRefusalError, match="outside PLUGINS_NODE_UID_RANGE"):
        operations.handle(protocol.KillUid(uid=PLUGIN_UID + 10), [])


@pytest.mark.parametrize("uid", [0, 10000, 65534])
def test_root_the_agent_and_nobody_are_never_plugin_uids(operations, uid):
    request = protocol.KillUid.model_construct(operation="kill_uid", uid=uid)

    with pytest.raises(LauncherRefusalError):
        operations.handle(request, [])


# SO_ACCEPTCONN, which the launcher checks first, is Linux-only.
@pytest.mark.linux
@pytest.mark.parametrize(
    "executable",
    [
        "/bin/sh",
        "/var/lib/es_plugins/venvs/other/0.2.0/bin/python",
        "/var/lib/es_plugins/venvs/weather/../other/bin/python",
        "venvs/weather/0.2.0/bin/python",
    ],
)
def test_a_command_outside_the_plugins_venvs_is_refused(layout, unprivileged_setup, executable):
    operations = LauncherOperations(
        layout, UidRange(PLUGIN_UID, PLUGIN_UID), unprivileged_setup, ProcessTable()
    )
    executable = executable.replace("/var/lib/es_plugins", str(layout.data_root))
    listener = listening_tcp_socket()
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(LauncherRefusalError, match="is not inside"):
            operations.handle(spawn_request(argv=[executable]), [write_end, listener.fileno()])
    finally:
        listener.close()
        os.close(read_end)
        os.close(write_end)


def test_a_request_missing_its_descriptor_is_refused(operations):
    with pytest.raises(LauncherRefusalError, match="takes 1 descriptor"):
        operations.handle(protocol.WriteRuntimeFile(plugin="weather", uid=PLUGIN_UID), [])


def test_a_spawn_without_the_listening_socket_is_refused(operations):
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(LauncherRefusalError, match="takes 2 descriptor"):
            operations.handle(spawn_request(), [write_end])
    finally:
        os.close(read_end)
        os.close(write_end)


def listening_tcp_socket() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    return listener


def bound_tcp_socket() -> socket.socket:
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.bind(("127.0.0.1", 0))
    return bound


def udp_socket() -> socket.socket:
    datagram = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    datagram.bind(("127.0.0.1", 0))
    return datagram


def unix_stream_socket() -> socket.socket:
    first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    second.close()
    return first


# SO_ACCEPTCONN, which the launcher checks first, is Linux-only.
@pytest.mark.linux
@pytest.mark.parametrize(
    ("make_candidate", "reason"),
    [
        (bound_tcp_socket, "not a listening socket"),
        (udp_socket, "must be a TCP socket"),
        (unix_stream_socket, "must be a TCP socket"),
    ],
)
def test_a_listen_descriptor_that_is_not_a_listening_tcp_socket_is_refused(
    operations, make_candidate, reason
):
    candidate = make_candidate()
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(LauncherRefusalError, match=reason):
            operations.handle(spawn_request(), [write_end, candidate.fileno()])
        # The launcher looked at a copy: the agent's socket is still open.
        os.fstat(candidate.fileno())
    finally:
        candidate.close()
        os.close(read_end)
        os.close(write_end)


def test_a_pipe_in_place_of_the_listening_socket_is_refused(operations):
    output_read, output_write = os.pipe()
    other_read, other_write = os.pipe()
    try:
        with pytest.raises(LauncherRefusalError, match="is not a socket"):
            operations.handle(spawn_request(), [output_write, other_read])
    finally:
        for descriptor in (output_read, output_write, other_read, other_write):
            os.close(descriptor)


def test_a_socket_in_place_of_the_output_pipe_is_refused(operations):
    listener = listening_tcp_socket()
    try:
        with pytest.raises(LauncherRefusalError, match="output descriptor must be a pipe"):
            operations.handle(spawn_request(), [listener.fileno(), listener.fileno()])
    finally:
        listener.close()


def test_the_uid_range_follows_django_apps_start_up_check():
    assert UidRange.parse("20000-20999") == UidRange(20000, 20999)
    for text in ("10000-10999", "20000-20005", "20999-20000", "20000-60000", "none", ""):
        with pytest.raises(ValueError):
            UidRange.parse(text)


class RunningServer:
    """A launcher server answering in a thread, as PID 1 does in its loop."""

    def __init__(self, socket_path, operations, agent_uid):
        self.server = LauncherServer(socket_path, operations, agent_uid=agent_uid)
        self.server.listen(group=os.getgid())
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            self.server.serve_once(timeout=0.05)

    def stop(self):
        self._stop.set()
        self._thread.join()
        self.server.close()


# The UID the end-to-end tests serve: the test's own, or a plugin UID when they run as root.
SERVED_UID = os.getuid() or PLUGIN_UID


@pytest.fixture
def own_uid_operations(layout, unprivileged_setup):
    return LauncherOperations(
        layout, UidRange(SERVED_UID, SERVED_UID), unprivileged_setup, OwnProcessTable()
    )


@pytest.mark.linux
async def test_the_agent_peer_is_served_end_to_end(layout, own_uid_operations):
    running = RunningServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid())
    client = LauncherClient(layout.launcher_socket)
    not_listening = bound_tcp_socket()
    read_end, write_end = os.pipe()
    try:
        await client.connect()
        await client.prepare_plugin("weather", SERVED_UID)
        await client.write_runtime_file("weather", SERVED_UID, b'{"format":1}')

        runtime_file = layout.runtime_file("weather")
        assert stat.S_IMODE(os.stat(runtime_file).st_mode) == 0o400
        assert os.stat(runtime_file).st_uid == SERVED_UID
        assert await client.exit_status(999_999) is None
        with pytest.raises(LauncherError, match="outside PLUGINS_NODE_UID_RANGE"):
            await client.kill_uid(SERVED_UID + 1)
        # Both of a spawn's descriptors crossed the socket: the launcher examined the second.
        with pytest.raises(LauncherError, match="not a listening socket"):
            await client.spawn(
                "weather",
                SERVED_UID,
                [str(layout.plugin_venv("weather", "0.2.0") / "bin" / "python")],
                {},
                0,
                write_end,
                not_listening.fileno(),
            )
    finally:
        client.close()
        running.stop()
        not_listening.close()
        os.close(read_end)
        os.close(write_end)


@pytest.mark.linux
async def test_a_peer_with_another_uid_is_refused(layout, own_uid_operations):
    running = RunningServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid() + 1)
    client = LauncherClient(layout.launcher_socket)
    try:
        await client.connect()
        with pytest.raises(LauncherError, match="connection"):
            await client.prepare_plugin("weather", SERVED_UID)
    finally:
        client.close()
        running.stop()

    assert not layout.plugin_home("weather").exists()


@pytest.mark.linux
def test_a_failed_step_in_the_child_comes_back_as_the_reason(tmp_path):
    # Without root the switch to another user is what fails; as root, the missing program.
    expected = "execve: FileNotFoundError" if os.geteuid() == 0 else "user switch"
    with pytest.raises(SpawnError, match=expected):
        spawn_process(
            SpawnSpec(
                uid=os.getuid(),
                gid=os.getgid(),
                argv=[str(tmp_path / "missing")],
                environment={},
                working_directory=tmp_path,
            )
        )


def read_status(pid):
    with open(f"/proc/{pid}/status") as status_file:
        return dict(line.rstrip("\n").split(":\t", 1) for line in status_file if ":\t" in line)


@pytest.mark.root
def test_a_plugin_process_runs_without_privileges_and_with_its_limits(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    read_end, write_end = os.pipe()
    pid = spawn_process(
        SpawnSpec(
            uid=PLUGIN_UID,
            gid=PLUGIN_UID,
            argv=["/bin/sleep", "30"],
            environment={"USER": "weather"},
            working_directory=layout.plugin_home("weather"),
            nice=10,
            resource_limits=((resource.RLIMIT_NPROC, 64), (resource.RLIMIT_NOFILE, 1024)),
            oom_score_adj=PLUGIN_OOM_SCORE_ADJ,
            output_descriptor=write_end,
        )
    )
    os.close(write_end)
    try:
        time.sleep(0.2)
        status = read_status(pid)
        assert status["Uid"].split() == [str(PLUGIN_UID)] * 4
        assert status["Gid"].split() == [str(PLUGIN_UID)] * 4
        assert status["Groups"].strip() == ""
        assert status["CapEff"] == status["CapPrm"] == "0000000000000000"
        assert status["NoNewPrivs"] == "1"
        assert Path(f"/proc/{pid}/oom_score_adj").read_text().strip() == str(PLUGIN_OOM_SCORE_ADJ)
        assert os.getsid(pid) == pid
        assert os.getpriority(os.PRIO_PROCESS, pid) == 10
        limits = Path(f"/proc/{pid}/limits").read_text()
        assert "Max processes             64                   64" in limits
    finally:
        kill_uid(PLUGIN_UID, ProcessTable(), reap=lambda: None)
        os.waitpid(pid, 0)
        os.close(read_end)


@pytest.mark.root
def test_a_plugin_process_gets_exactly_the_environment_it_is_given(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    read_end, write_end = os.pipe()
    pid = spawn_process(
        SpawnSpec(
            uid=PLUGIN_UID,
            gid=PLUGIN_UID,
            argv=["/usr/bin/env"],
            environment={"USER": "weather", "PORT": "20001"},
            working_directory=layout.plugin_home("weather"),
            output_descriptor=write_end,
        )
    )
    os.close(write_end)
    with os.fdopen(read_end, "rb") as output:
        printed = output.read()
    os.waitpid(pid, 0)

    assert sorted(printed.decode().splitlines()) == ["PORT=20001", "USER=weather"]


@pytest.mark.root
def test_killing_by_uid_reaches_children_that_left_the_session(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    script = "import os, time\nfor _ in range(3):\n    if os.fork() == 0:\n        os.setsid(); time.sleep(60)\ntime.sleep(60)\n"
    pid = spawn_process(
        SpawnSpec(
            uid=PLUGIN_UID,
            gid=PLUGIN_UID,
            argv=[SYSTEM_PYTHON, "-c", script],
            environment={},
            working_directory=layout.plugin_home("weather"),
        )
    )
    table = ProcessTable()
    deadline = time.monotonic() + 5
    while len(table.living_pids_of_uid(PLUGIN_UID)) < 4 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(table.living_pids_of_uid(PLUGIN_UID)) == 4

    outcome = kill_uid(PLUGIN_UID, table, reap=lambda: None)

    os.waitpid(pid, 0)
    assert outcome.remaining == ()
    assert table.living_pids_of_uid(PLUGIN_UID) == []


@pytest.mark.linux
def test_an_exit_is_remembered_whoever_reaped_it(operations):
    child = os.fork()
    if child == 0:
        os._exit(7)
    time.sleep(0.2)

    operations.reap()

    assert operations.exit_code_of(child) == 7


@pytest.mark.linux
async def test_an_unexpected_error_answers_a_failure_and_the_launcher_keeps_serving(
    layout, own_uid_operations, monkeypatch
):
    def broken(request, descriptors):
        raise RuntimeError("a bug in the launcher")

    running = RunningServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid())
    client = LauncherClient(layout.launcher_socket)
    try:
        await client.connect()
        monkeypatch.setattr(own_uid_operations, "handle", broken)
        with pytest.raises(LauncherError, match="failed the request"):
            await client.prepare_plugin("weather", SERVED_UID)
        monkeypatch.undo()

        await client.prepare_plugin("weather", SERVED_UID)
    finally:
        client.close()
        running.stop()

    assert layout.plugin_home("weather").is_dir()


# Leaves fd 0 free, so the error pipe the spawn opens would land on fds 0 and 3 if nothing
# moved it; the listening socket waits at fd 10.
LOW_DESCRIPTORS_SCRIPT = """
import os, socket, sys
from es_plugins.launcher.process_spawn import SpawnError, SpawnSpec, spawn_process
os.closerange(3, 1024)
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
os.dup2(listener.detach(), 10, inheritable=False)
os.close(3)
os.close(0)
try:
    spawn_process(SpawnSpec(uid=os.getuid(), gid=os.getgid(), argv=[sys.argv[1]],
                            environment={}, working_directory="/", listen_descriptor=10))
except SpawnError as error:
    print("refused:", error)
else:
    print("started")
"""


@pytest.mark.linux
def test_a_failure_after_the_socket_is_placed_still_comes_back_as_the_reason(tmp_path):
    finished = subprocess.run(
        [sys.executable, "-c", LOW_DESCRIPTORS_SCRIPT, str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.startswith("refused:"), finished.stdout


def plugin_python(layout) -> str:
    """A plugin venv's `bin/python`, as the launcher accepts it, pointing at the system's."""
    venv_bin = layout.plugin_venv("weather", "0.2.0") / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").symlink_to(SYSTEM_PYTHON)
    return str(venv_bin / "python")


# The SDK's name for the variable: the launcher spells it without importing the SDK, so this
# test is what keeps the two equal.
SERVE_ON_INHERITED_SOCKET = (
    "import os, socket; "
    f"fd = int(os.environ['{LISTEN_FD_ENVIRONMENT_VARIABLE}']); "
    "listener = socket.socket(fileno=fd); "
    "print(os.get_inheritable(fd), listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), "
    "sorted(int(name) for name in os.listdir('/proc/self/fd')), flush=True); "
    "connection, _ = listener.accept(); "
    "connection.sendall(f'served by {os.getuid()}'.encode()); "
    "connection.close()"
)


@pytest.mark.root
def test_a_plugin_process_serves_on_the_listening_socket_it_inherits_as_fd_3(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    operations = LauncherOperations(
        layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable()
    )
    listener = listening_tcp_socket()
    read_end, write_end = os.pipe()
    request = spawn_request(
        argv=[plugin_python(layout), "-I", "-c", SERVE_ON_INHERITED_SOCKET],
        # The agent cannot choose the descriptor: the launcher sets the variable itself.
        environment={"USER": "weather", LISTEN_FD_ENVIRONMENT_VARIABLE: "7"},
    )
    result, (pidfd,) = operations.handle(request, [write_end, listener.fileno()])
    os.close(write_end)
    try:
        with socket.create_connection(listener.getsockname(), timeout=10) as connection:
            answer = connection.recv(100)
        with os.fdopen(read_end, "rb") as output:
            printed = output.read().decode()
    finally:
        os.close(pidfd)
        kill_uid(PLUGIN_UID, ProcessTable(), reap=lambda: None)
        os.waitpid(result.pid, 0)
        listener.close()

    assert answer == f"served by {PLUGIN_UID}".encode()
    # Inheritable, listening, and with nothing of the launcher's besides 0, 1, 2 and 3 (4 is
    # the directory listdir itself opened).
    assert printed.strip() == "True 1 [0, 1, 2, 3, 4]"
    assert LISTEN_FD == 3


@pytest.mark.root
def test_the_process_limit_is_in_force_when_the_user_switches(layout):
    # Set after setresuid, the limit would not be checked at execve at all: the launcher's
    # own limit applies at the switch, so every spawn below would start.
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    started = []
    refusal = None
    try:
        for _ in range(5):
            try:
                started.append(
                    spawn_process(
                        SpawnSpec(
                            uid=PLUGIN_UID,
                            gid=PLUGIN_UID,
                            argv=["/bin/sleep", "30"],
                            environment={},
                            working_directory=layout.plugin_home("weather"),
                            resource_limits=((resource.RLIMIT_NPROC, 2),),
                        )
                    )
                )
            except SpawnError as error:
                refusal = str(error)
                break
    finally:
        kill_uid(PLUGIN_UID, ProcessTable(), reap=lambda: None)
        for pid in started:
            os.waitpid(pid, 0)

    # Kernels differ by one in where they draw the line (count above or at the limit).
    assert len(started) in (2, 3)
    assert refusal.startswith("execve: BlockingIOError")


def agent_stand_in(socket_path, requests):
    """Fork a process that sends `requests` to the launcher, as the agent does when it stops."""
    pid = os.fork()
    if pid == 0:
        try:

            async def stop_plugins():
                client = LauncherClient(socket_path)
                for request in requests:
                    await request(client)
                client.close()

            asyncio.run(stop_plugins())
            os._exit(0)
        except BaseException:
            os._exit(1)
    return pid


@pytest.mark.linux
def test_the_launcher_answers_the_agent_until_it_has_exited(layout, own_uid_operations):
    server = LauncherServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid())
    server.listen(group=os.getgid())

    async def wait_then_ask(client):
        await asyncio.sleep(0.5)
        await client.prepare_plugin("weather", SERVED_UID)
        assert await client.exit_status(999_999) is None

    agent = agent_stand_in(layout.launcher_socket, [wait_then_ask])
    try:
        exited = serve_until_agent_exits(server, own_uid_operations, agent, timeout_seconds=10)
    finally:
        server.close()

    assert exited
    assert own_uid_operations.exit_code_of(agent) == 0
    assert layout.plugin_home("weather").is_dir()


@pytest.mark.linux
def test_the_launcher_stops_waiting_for_an_agent_that_does_not_exit(layout, own_uid_operations):
    server = LauncherServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid())
    server.listen(group=os.getgid())

    async def hang(client):
        await asyncio.sleep(30)

    agent = agent_stand_in(layout.launcher_socket, [hang])
    try:
        assert not serve_until_agent_exits(server, own_uid_operations, agent, timeout_seconds=0.5)
    finally:
        os.kill(agent, 9)
        os.waitpid(agent, 0)
        server.close()


@pytest.mark.linux
async def test_a_cancelled_call_drops_the_connection_and_the_next_call_reconnects(tmp_path):
    socket_path = tmp_path / "launcher.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(socket_path))
    listener.listen(2)
    connections = []

    def answer(connection, remaining):
        result = {"ok": True, "result": {"rounds": 1, "remaining": remaining}}
        connection.send(json.dumps(result).encode())

    def serve():
        first, _ = listener.accept()
        connections.append(first)
        first.recv(protocol.MAX_MESSAGE_BYTES)  # the request whose caller gave up
        second, _ = listener.accept()
        connections.append(second)
        # The late answer to the abandoned request: it must never reach the next call.
        try:
            answer(first, [4242])
        except OSError:
            pass
        second.recv(protocol.MAX_MESSAGE_BYTES)
        answer(second, [])

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = LauncherClient(socket_path)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.kill_uid(PLUGIN_UID), 0.3)

        assert await asyncio.wait_for(client.kill_uid(PLUGIN_UID), 5) == []
    finally:
        client.close()
        thread.join(5)
        for connection in connections:
            connection.close()
        listener.close()

    assert len(connections) == 2


@pytest.mark.parametrize("limits", [{"max_bytes": 0, "max_files": 1}, {"max_bytes": 1, "max_files": 0}])
def test_a_disk_measurement_without_limits_is_refused(limits):
    with pytest.raises(ValidationError):
        protocol.decode_request(
            json.dumps({"operation": "measure_disk", "plugin": "weather", "uid": PLUGIN_UID, **limits}).encode()
        )


def read_usage(descriptor: int) -> DiskUsage:
    with os.fdopen(descriptor, "rb") as result:
        return DiskUsage.from_json(result.read())


# The test serves the launcher from a thread, so it forks the helper from a threaded process;
# the real launcher is single-threaded.
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.linux
async def test_the_agent_gets_a_plugins_disk_use_through_the_launcher(layout, own_uid_operations):
    running = RunningServer(layout.launcher_socket, own_uid_operations, agent_uid=os.getuid())
    client = LauncherClient(layout.launcher_socket)
    try:
        await client.prepare_plugin("weather", SERVED_UID)
        (layout.plugin_home("weather") / "notes.txt").write_bytes(b"\x01" * (2 * 1024 * 1024))

        usage = read_usage(await client.measure_disk("weather", SERVED_UID, 10**12, 10**9))
        with pytest.raises(LauncherError, match="outside PLUGINS_NODE_UID_RANGE"):
            await client.measure_disk("weather", SERVED_UID + 1, 1, 1)
    finally:
        client.close()
        running.stop()

    # HOME, its tmp and the file.
    assert usage.files == 3
    assert usage.bytes >= 2 * 1024 * 1024
    assert usage.problem is None


IDENTITY_PROBE = """
import os, sys
from es_plugins.launcher.disk_measurement import take_filesystem_identity
take_filesystem_identity(int(sys.argv[1]), int(sys.argv[1]))
uid = [line.split()[1:] for line in open("/proc/self/status") if line.startswith("Uid:")][0]
def can_list(path):
    try:
        os.listdir(path)
        return "lists"
    except PermissionError:
        return "refused"
print(" ".join(uid), can_list(sys.argv[2]), can_list(sys.argv[3]))
"""


@pytest.mark.root
def test_the_measuring_helper_reads_as_the_plugin_but_stays_root_for_signals(layout, tmp_path):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    roots_own = tmp_path / "roots-own"
    roots_own.mkdir(mode=0o700)

    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            IDENTITY_PROBE,
            str(PLUGIN_UID),
            str(layout.plugin_home("weather")),
            str(roots_own),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )

    # Real, effective and saved UIDs stay 0 (the plugin cannot signal it); the filesystem UID
    # is the plugin's, so it reads the plugin's 0700 HOME and not root's own 0700 directory.
    assert finished.stdout.split() == ["0", "0", "0", str(PLUGIN_UID), "lists", "refused"], finished.stderr


@pytest.mark.root
def test_root_measures_a_plugins_home_as_the_plugin(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    data = layout.plugin_home("weather") / "data.bin"
    data.write_bytes(b"\x01" * (3 * 1024 * 1024))
    os.chown(data, PLUGIN_UID, PLUGIN_UID)
    operations = LauncherOperations(
        layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable()
    )

    _, (result_pipe,) = operations.handle(
        protocol.MeasureDisk(plugin="weather", uid=PLUGIN_UID, max_bytes=10**12, max_files=10**9),
        [],
    )
    usage = read_usage(result_pipe)
    operations.reap()

    assert (usage.files, usage.problem) == (3, None)
    assert usage.bytes >= 3 * 1024 * 1024


def test_a_removal_request_is_decoded():
    request = protocol.decode_request(json.dumps({"operation": "remove_plugin", "plugin": "weather", "uid": PLUGIN_UID}).encode())

    assert request == protocol.RemovePlugin(plugin="weather", uid=PLUGIN_UID)


@pytest.mark.parametrize(
    "overrides",
    [{"plugin": "../weather"}, {"plugin": "Weather"}, {"plugin": ""}, {"uid": 0}, {"uid": -3}, {"unexpected": True}],
)
def test_a_removal_of_something_that_is_not_a_plugin_is_refused(overrides):
    document = {"operation": "remove_plugin", "plugin": "weather", "uid": PLUGIN_UID, **overrides}

    with pytest.raises(ValidationError):
        protocol.decode_request(json.dumps(document).encode())


def test_a_removal_for_a_uid_outside_the_range_is_refused(operations):
    with pytest.raises(LauncherRefusalError, match="outside PLUGINS_NODE_UID_RANGE"):
        operations.handle(protocol.RemovePlugin(plugin="weather", uid=PLUGIN_UID + 10), [])


MQ_OPEN_AS_PLUGIN = """
import ctypes, os, sys
libc = ctypes.CDLL("librt.so.1", use_errno=True)
libc.mq_open.restype = ctypes.c_int
descriptor = libc.mq_open(b"/plugin-queue", os.O_CREAT | os.O_RDWR, 0o600, None)
print(descriptor, ctypes.get_errno())
"""


@pytest.mark.root
def test_a_plugin_process_cannot_create_a_posix_message_queue(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    read_end, write_end = os.pipe()
    pid = spawn_process(
        SpawnSpec(
            uid=PLUGIN_UID,
            gid=PLUGIN_UID,
            argv=[SYSTEM_PYTHON, "-I", "-c", MQ_OPEN_AS_PLUGIN],
            environment={},
            working_directory=layout.plugin_home("weather"),
            nice=0,
            resource_limits=PLUGIN_RESOURCE_LIMITS,
            oom_score_adj=PLUGIN_OOM_SCORE_ADJ,
            output_descriptor=write_end,
        )
    )
    os.close(write_end)
    os.waitpid(pid, 0)
    with os.fdopen(read_end) as output:
        descriptor, error = output.read().split()

    # EMFILE: the queue would take more than RLIMIT_MSGQUEUE (0) of the UID's queue memory.
    assert (int(descriptor), int(error)) == (-1, errno.EMFILE)


def _fill_home(home: Path, files: int) -> None:
    """Runs as the plugin: `files` empty files in HOME, a thousand to a directory."""
    for index in range(files):
        directory = home / "many" / str(index // 1000)
        if index % 1000 == 0:
            directory.mkdir(parents=True)
        (directory / str(index)).touch()


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.root
async def test_the_launcher_answers_other_requests_while_a_removal_deletes_a_large_home(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    operations = LauncherOperations(layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable())
    running = RunningServer(layout.launcher_socket, operations, agent_uid=os.getuid())
    removing_client, other_client = LauncherClient(layout.launcher_socket), LauncherClient(layout.launcher_socket)
    try:
        await removing_client.prepare_plugin("weather", PLUGIN_UID)
        assert run_as_user(PLUGIN_UID, lambda: _fill_home(layout.plugin_home("weather"), 50_000))
        removal = asyncio.create_task(removing_client.remove_plugin("weather", PLUGIN_UID, timeout_seconds=120))
        await asyncio.sleep(0.05)

        await other_client.exit_status(4_000_000)
        answered_while_removing = not removal.done()
        await removal
    finally:
        removing_client.close()
        other_client.close()
        running.stop()

    assert answered_while_removing
    assert not os.path.lexists(layout.plugin_home("weather"))
    assert not os.path.lexists(layout.plugin_code_root("weather"))


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.root
async def test_a_removal_the_launcher_cannot_finish_comes_back_as_its_reason(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    operations = LauncherOperations(layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable())
    running = RunningServer(layout.launcher_socket, operations, agent_uid=os.getuid())
    client = LauncherClient(layout.launcher_socket)
    try:
        await client.prepare_plugin("weather", PLUGIN_UID)
        (layout.plugin_venv("weather", "0.2.0") / "bin").mkdir(parents=True)

        with pytest.raises(LauncherError, match="is not empty"):
            await client.remove_plugin("weather", PLUGIN_UID, timeout_seconds=60)
    finally:
        client.close()
        running.stop()


def test_a_prune_request_is_decoded():
    request = protocol.decode_request(
        json.dumps({"operation": "prune_code", "plugin": "weather", "uid": PLUGIN_UID, "keep_version": "0.7.0"}).encode()
    )

    assert request == protocol.PruneCode(plugin="weather", uid=PLUGIN_UID, keep_version="0.7.0")


@pytest.mark.parametrize(
    "overrides",
    [{"keep_version": ".."}, {"keep_version": "0.7.0/../x"}, {"keep_version": ""}, {"plugin": "../weather"}, {"uid": 0}],
)
def test_a_prune_of_something_that_is_not_one_plugins_version_is_refused(overrides):
    document = {"operation": "prune_code", "plugin": "weather", "uid": PLUGIN_UID, "keep_version": "0.7.0", **overrides}

    with pytest.raises(ValidationError):
        protocol.decode_request(json.dumps(document).encode())


def test_a_prune_for_a_uid_outside_the_range_is_refused(operations):
    with pytest.raises(LauncherRefusalError, match="outside PLUGINS_NODE_UID_RANGE"):
        operations.handle(protocol.PruneCode(plugin="weather", uid=PLUGIN_UID + 10, keep_version="0.7.0"), [])


def test_a_temporary_refusal_says_so_and_a_permanent_one_does_not():
    assert json.loads(protocol.encode_failure("busy", temporary=True)) == {"ok": False, "error": "busy", "temporary": True}
    assert json.loads(protocol.encode_failure("no")) == {"ok": False, "error": "no", "temporary": False}


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.root
async def test_a_second_removal_while_the_first_runs_is_answered_as_temporary(layout):
    from es_plugins.agent.launcher_client import LauncherUnavailableError

    setup = DirectorySetup(layout)
    setup.prepare_tree()
    operations = LauncherOperations(layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable())
    running = RunningServer(layout.launcher_socket, operations, agent_uid=os.getuid())
    first, second = LauncherClient(layout.launcher_socket), LauncherClient(layout.launcher_socket)
    try:
        await first.prepare_plugin("weather", PLUGIN_UID)
        assert run_as_user(PLUGIN_UID, lambda: _fill_home(layout.plugin_home("weather"), 50_000))
        removal = asyncio.create_task(first.remove_plugin("weather", PLUGIN_UID, timeout_seconds=120))
        await asyncio.sleep(0.05)

        with pytest.raises(LauncherUnavailableError, match="already being removed"):
            await second.remove_plugin("weather", PLUGIN_UID, timeout_seconds=120)
        await removal
        await second.remove_plugin("weather", PLUGIN_UID, timeout_seconds=120)
    finally:
        first.close()
        second.close()
        running.stop()


@pytest.mark.root
def test_root_prunes_a_plugins_code_but_the_version_it_runs(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin("weather", PLUGIN_UID)
    operations = LauncherOperations(layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable())
    for version in ("0.6.0", "0.7.0"):
        (layout.plugin_code("weather", version) / "backend").mkdir(parents=True)

    result, _ = operations.handle(protocol.PruneCode(plugin="weather", uid=PLUGIN_UID, keep_version="0.7.0"), [])

    assert result.removed == ["0.6.0"]
    assert os.listdir(layout.plugin_code_root("weather")) == ["0.7.0"]

