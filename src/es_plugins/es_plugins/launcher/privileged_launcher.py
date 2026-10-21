"""es-launcher: PID 1 of the es_plugins container, root with `SETUID`, `SETGID`, `CHOWN` only.

It prepares the node's directories, starts the agent as UID 10000, and then serves the
agent's requests (see `protocol`) on a `SOCK_SEQPACKET` socket in `/run/es_launcher/`,
whose directory only root and group 10000 may enter. It answers only a peer whose UID,
as `SO_PEERCRED` reports it, is the agent's; it refuses any UID outside
`PLUGINS_NODE_UID_RANGE` and any path outside the node's directories.

As PID 1 it also reaps every orphan in the container, and remembers the exit status of the
processes it started so the agent can report why one stopped.
"""

import os
import resource
import select
import signal
import socket
import stat
import struct
import time
from collections import OrderedDict
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from es_plugins.launcher import protocol
from es_plugins.launcher.directory_setup import DirectorySetup, DirectorySetupError
from es_plugins.launcher.disk_measurement import start_measurement
from es_plugins.launcher.ipc_cleanup import IpcCleanupError
from es_plugins.launcher.kill_by_uid import kill_uid, signal_uid
from es_plugins.launcher.plugin_removal import start_removal
from es_plugins.launcher.process_spawn import LISTEN_FD, SpawnError, SpawnSpec, spawn_process
from es_plugins.layout import NodeLayout
from es_plugins.process_table import ProcessTable
from es_plugins.runtime.runtime_file_writer import (
    RuntimeFileError,
    read_content_descriptor,
    write_runtime_file,
)
from es_plugins.uid_range import UidRange

# Linux's number for it: the launcher runs only on Linux, but its tests import it everywhere.
_RLIMIT_MSGQUEUE = getattr(resource, "RLIMIT_MSGQUEUE", 12)
PLUGIN_RESOURCE_LIMITS = (
    (resource.RLIMIT_NPROC, 64),
    (resource.RLIMIT_NOFILE, 1024),
    (resource.RLIMIT_CORE, 0),
    # No POSIX message queues: they outlive the process like System V IPC objects, and no
    # listing shows them, so a removed plugin's could not be found to delete.
    (_RLIMIT_MSGQUEUE, 0),
)
PLUGIN_OOM_SCORE_ADJ = 800
MAX_REMEMBERED_EXIT_STATUSES = 4096
_PEER_CREDENTIALS = struct.Struct("3i")
_LOOP_TIMEOUT_SECONDS = 0.5


class LauncherRefusalError(Exception):
    """The request is well-formed but not allowed; the message goes back to the agent."""


class LauncherOperations:
    """Carries out one validated request. Socket handling lives in `LauncherServer`."""

    def __init__(
        self,
        layout: NodeLayout,
        uid_range: UidRange,
        directory_setup: DirectorySetup,
        process_table: ProcessTable,
    ):
        self._layout = layout
        self._uid_range = uid_range
        self._directory_setup = directory_setup
        self._process_table = process_table
        self._exit_statuses: OrderedDict[int, int] = OrderedDict()

    def handle(self, request: protocol.LauncherRequest, descriptors: list[int]):
        """Return `(result, descriptors to send back)`.

        Raises:
            LauncherRefusalError: The request names a UID or path the launcher does not serve,
                or a step failed in a way the agent should hear about.
        """
        expected = protocol.DESCRIPTORS_EXPECTED.get(request.operation, 0)
        if len(descriptors) != expected:
            raise LauncherRefusalError(
                f"{request.operation} takes {expected} descriptor(s), got {len(descriptors)}"
            )
        if hasattr(request, "uid") and request.uid not in self._uid_range:
            raise LauncherRefusalError(f"UID {request.uid} is outside PLUGINS_NODE_UID_RANGE")
        try:
            return self._dispatch(request, descriptors)
        except (DirectorySetupError, RuntimeFileError, SpawnError, IpcCleanupError) as error:
            raise LauncherRefusalError(str(error)) from None
        except OSError as error:
            raise LauncherRefusalError(f"{request.operation} failed: {error}") from None

    def _dispatch(self, request: protocol.LauncherRequest, descriptors: list[int]):
        match request:
            case protocol.PreparePlugin(plugin=plugin, uid=uid):
                self._directory_setup.prepare_plugin(plugin, uid)
                return None, []
            case protocol.InstallCode(plugin=plugin, version=version):
                self._directory_setup.install_code(plugin, version)
                return None, []
            case protocol.WriteRuntimeFile(plugin=plugin, uid=uid):
                content = read_content_descriptor(descriptors[0])
                write_runtime_file(self._layout.plugin_run_directory(plugin), uid, uid, content)
                return None, []
            case protocol.Spawn():
                return self._spawn(request, descriptors[0], descriptors[1])
            case protocol.TerminateUid(uid=uid):
                signal_uid(uid, signal.SIGTERM)
                return None, []
            case protocol.KillUid(uid=uid):
                outcome = kill_uid(uid, self._process_table, reap=self.reap)
                return protocol.KillResult(
                    rounds=outcome.rounds, remaining=list(outcome.remaining)
                ), []
            case protocol.ExitStatus(pid=pid):
                return protocol.ExitStatusResult(status=self.exit_code_of(pid)), []
            case protocol.MeasureDisk(plugin=plugin, uid=uid):
                result_pipe = start_measurement(
                    self._layout.plugin_home(plugin),
                    uid,
                    uid,
                    max_bytes=request.max_bytes,
                    max_files=request.max_files,
                    process_table=self._process_table,
                )
                return None, [result_pipe]
            case protocol.PurgeData(plugin=plugin, uid=uid):
                kill_uid(uid, self._process_table, reap=self.reap)
                self._directory_setup.purge_plugin_data(plugin, uid)
                return None, []
            case protocol.RemovePlugin(plugin=plugin, uid=uid):
                return None, [self._start_removal(plugin, uid)]
        raise LauncherRefusalError(f"unknown operation {request.operation}")

    def _start_removal(self, plugin: str, uid: int) -> int:
        """Kill the UID's processes, then start the helper that deletes the rest (see
        `plugin_removal`); return the pipe its result arrives on. Nothing is deleted while a
        process lives."""
        outcome = kill_uid(uid, self._process_table, reap=self.reap)
        if outcome.remaining:
            raise LauncherRefusalError(
                f"{len(outcome.remaining)} process(es) of UID {uid} are still alive after SIGKILL"
            )
        return start_removal(self._directory_setup, plugin, uid)

    def _spawn(self, request: protocol.Spawn, output_descriptor: int, listen_descriptor: int):
        if not stat.S_ISFIFO(os.fstat(output_descriptor).st_mode):
            raise LauncherRefusalError("the output descriptor must be a pipe")
        self._check_listen_socket(listen_descriptor)
        executable = request.argv[0]
        venvs = self._layout.plugin_venvs(request.plugin)
        if os.path.normpath(executable) != executable or venvs not in Path(executable).parents:
            raise LauncherRefusalError(f"{executable} is not inside {venvs}")
        pid = spawn_process(
            SpawnSpec(
                uid=request.uid,
                gid=request.uid,
                argv=request.argv,
                # The launcher, not the agent, names the fd the socket lands on.
                environment={**request.environment, "EPICSTAFF_PLUGIN_LISTEN_FD": str(LISTEN_FD)},
                working_directory=self._layout.plugin_home(request.plugin),
                nice=request.nice,
                resource_limits=PLUGIN_RESOURCE_LIMITS,
                oom_score_adj=PLUGIN_OOM_SCORE_ADJ,
                output_descriptor=output_descriptor,
                listen_descriptor=listen_descriptor,
            )
        )
        # A pidfd lets the agent wait for this process although it is not its parent. It
        # grants nothing else: signalling through it needs the same rights as kill(2).
        return protocol.SpawnResult(pid=pid), [os.pidfd_open(pid)]

    @staticmethod
    def _check_listen_socket(descriptor: int) -> None:
        """Refuse anything but a bound, listening TCP socket for the plugin's fd 3."""
        try:
            # Wraps a dup of the fd; closing it closes only the dup, never the agent's socket.
            attached = socket.socket(fileno=os.dup(descriptor))
        except OSError as error:
            raise LauncherRefusalError(f"the listen descriptor is not a socket: {error}") from None
        try:
            if attached.type != socket.SOCK_STREAM or attached.family not in (
                socket.AF_INET,
                socket.AF_INET6,
            ):
                raise LauncherRefusalError("the listen descriptor must be a TCP socket")
            if not attached.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
                raise LauncherRefusalError("the listen descriptor is not a listening socket")
        finally:
            attached.close()

    def exit_code_of(self, pid: int) -> int | None:
        """The exit code of a reaped child, whoever reaped it (the loop or a kill)."""
        self.reap()
        return self._exit_statuses.get(pid)

    def reap(self) -> list[tuple[int, int]]:
        """Collect every exited child; remember the statuses; return what was collected."""
        collected = []
        while True:
            try:
                pid, wait_status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            exit_code = os.waitstatus_to_exitcode(wait_status)
            collected.append((pid, exit_code))
            self._exit_statuses[pid] = exit_code
            while len(self._exit_statuses) > MAX_REMEMBERED_EXIT_STATUSES:
                self._exit_statuses.popitem(last=False)
        return collected


def peer_uid(connection: socket.socket) -> int:
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, _PEER_CREDENTIALS.size
    )
    _, uid, _ = _PEER_CREDENTIALS.unpack(credentials)
    return uid


class LauncherServer:
    """The socket side: accepts only the agent's UID and answers one packet per request."""

    def __init__(self, socket_path: Path, operations: LauncherOperations, *, agent_uid: int):
        self._socket_path = socket_path
        self._operations = operations
        self._agent_uid = agent_uid
        self._listener: socket.socket | None = None
        self._connections: list[socket.socket] = []

    def listen(self, group: int) -> None:
        """Bind the socket (0660, owned by root and `group`)."""
        self._socket_path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.bind(str(self._socket_path))
        os.chmod(self._socket_path, 0o660)
        os.chown(self._socket_path, os.getuid(), group)
        listener.listen(8)
        self._listener = listener

    def serve_once(self, timeout: float = _LOOP_TIMEOUT_SECONDS) -> None:
        """Wait up to `timeout` for activity and handle what arrived."""
        try:
            readable, _, _ = select.select([self._listener, *self._connections], [], [], timeout)
        except InterruptedError:
            return
        for ready in readable:
            if ready is self._listener:
                self._accept()
            else:
                self._answer(ready)

    def close(self) -> None:
        for connection in self._connections:
            connection.close()
        if self._listener is not None:
            self._listener.close()

    def _accept(self) -> None:
        connection, _ = self._listener.accept()
        uid = peer_uid(connection)
        if uid != self._agent_uid:
            logger.warning("Refused a launcher connection from UID {}", uid)
            connection.close()
            return
        self._connections.append(connection)

    def _answer(self, connection: socket.socket) -> None:
        try:
            packet, descriptors, flags, _ = socket.recv_fds(
                connection,
                protocol.MAX_MESSAGE_BYTES,
                protocol.MAX_DESCRIPTORS,
                socket.MSG_CMSG_CLOEXEC,
            )
        except OSError:
            packet, descriptors, flags = b"", [], 0
        if not packet:
            self._connections.remove(connection)
            connection.close()
            for descriptor in descriptors:
                os.close(descriptor)
            return
        reply_descriptors: list[int] = []
        try:
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                raise LauncherRefusalError("the request is larger than the launcher accepts")
            request = protocol.decode_request(packet)
            result, reply_descriptors = self._operations.handle(request, descriptors)
            reply = protocol.encode_success(result)
        except ValidationError as error:
            reply = protocol.encode_failure(f"invalid request: {error.errors()[0]['msg']}")
        except LauncherRefusalError as error:
            reply = protocol.encode_failure(str(error))
        except Exception:
            # PID 1 must outlive one bad request: its exit would stop every plugin on the node.
            logger.exception("The launcher failed a request")
            reply = protocol.encode_failure("the launcher failed the request; see its log")
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
        try:
            if reply_descriptors:
                socket.send_fds(connection, [reply], reply_descriptors)
            else:
                connection.send(reply)
        finally:
            for descriptor in reply_descriptors:
                os.close(descriptor)


def serve_until_agent_exits(
    server: "LauncherServer",
    operations: LauncherOperations,
    pid: int,
    timeout_seconds: float,
) -> bool:
    """Keep answering requests until `pid` has exited or the timeout passes; return whether it did.

    During shutdown the agent still asks the launcher to stop each plugin (SIGTERM, then
    SIGKILL after its grace period); the socket must stay served or those requests block.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        server.serve_once(timeout=0.2)
        if operations.exit_code_of(pid) is not None:
            return True
    return False
