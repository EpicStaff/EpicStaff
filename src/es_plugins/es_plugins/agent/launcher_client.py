"""The agent's side of the launcher socket (see `es_plugins.launcher.protocol`)."""

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from es_plugins.descriptors import read_pipe, write_all
from es_plugins.launcher import protocol
from es_plugins.launcher.plugin_removal import MAX_RESULT_BYTES


class LauncherError(Exception):
    """The launcher refused or failed a request; the message is the launcher's."""


class LauncherUnavailableError(LauncherError):
    """The launcher could not be reached, did not answer in time, or is still busy with the same
    plugin: trying again may succeed."""


@dataclass(frozen=True)
class SpawnedProcess:
    pid: int
    pidfd: int
    """Readable once the process has exited; the caller closes it."""


class LauncherClient:
    """One connection to the launcher; requests go one at a time, as the launcher serves them.

    If a call is cancelled, or the connection breaks, the socket is dropped and the next call
    reconnects: a reply the launcher may still send for the abandoned request is never read by
    a later call as its own.
    """

    def __init__(self, socket_path: Path):
        self._socket_path = socket_path
        self._socket: socket.socket | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        connection.setblocking(False)
        try:
            await asyncio.get_running_loop().sock_connect(connection, str(self._socket_path))
        except OSError as error:
            connection.close()
            raise LauncherUnavailableError(f"cannot reach the launcher: {error}") from None
        self._socket = connection

    def _drop_connection(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def close(self) -> None:
        self._drop_connection()

    async def prepare_plugin(self, plugin: str, uid: int) -> None:
        await self._call(protocol.PreparePlugin(plugin=plugin, uid=uid))

    async def install_code(self, plugin: str, uid: int, version: str) -> None:
        await self._call(protocol.InstallCode(plugin=plugin, uid=uid, version=version))

    async def prune_code(self, plugin: str, uid: int, keep_version: str) -> list[str]:
        """Have the launcher delete every version of the plugin's code but `keep_version`."""
        result, _ = await self._call(
            protocol.PruneCode(plugin=plugin, uid=uid, keep_version=keep_version)
        )
        return result["removed"]

    async def write_runtime_file(self, plugin: str, uid: int, content: bytes) -> None:
        """Have the launcher replace the plugin's runtime file with `content`."""
        memory_file = os.memfd_create("runtime-file", os.MFD_CLOEXEC)
        try:
            write_all(memory_file, content)
            await self._call(protocol.WriteRuntimeFile(plugin=plugin, uid=uid), [memory_file])
        finally:
            os.close(memory_file)

    async def spawn(
        self,
        plugin: str,
        uid: int,
        argv: list[str],
        environment: dict[str, str],
        nice: int,
        output_descriptor: int,
        listen_descriptor: int,
    ) -> SpawnedProcess:
        request = protocol.Spawn(
            plugin=plugin, uid=uid, argv=argv, environment=environment, nice=nice
        )
        result, descriptors = await self._call(
            request, [output_descriptor, listen_descriptor], expect=1
        )
        return SpawnedProcess(pid=result["pid"], pidfd=descriptors[0])

    async def terminate_uid(self, uid: int) -> None:
        await self._call(protocol.TerminateUid(uid=uid))

    async def kill_uid(self, uid: int) -> list[int]:
        """SIGKILL every process of `uid`; return the pids still alive (empty on success)."""
        result, _ = await self._call(protocol.KillUid(uid=uid))
        return result["remaining"]

    async def exit_status(self, pid: int) -> int | None:
        result, _ = await self._call(protocol.ExitStatus(pid=pid))
        return result["status"]

    async def measure_disk(self, plugin: str, uid: int, max_bytes: int, max_files: int) -> int:
        """Start measuring the plugin's HOME; return the pipe its `DiskUsage` JSON arrives on.

        The caller reads and closes the pipe. It closes without a result when the measurement
        fails or runs out of time.
        """
        request = protocol.MeasureDisk(
            plugin=plugin, uid=uid, max_bytes=max_bytes, max_files=max_files
        )
        _, descriptors = await self._call(request, expect=1)
        return descriptors[0]

    async def purge_data(self, plugin: str, uid: int) -> None:
        await self._call(protocol.PurgeData(plugin=plugin, uid=uid))

    async def remove_plugin(self, plugin: str, uid: int, *, timeout_seconds: float) -> None:
        """Have the launcher kill the UID's processes and delete what the node keeps for the plugin.

        The launcher answers at once with a pipe; its helper writes the outcome there when it has
        deleted everything, and the launcher serves other requests meanwhile.

        Raises:
            LauncherUnavailableError: No outcome within `timeout_seconds`, no connection, or a
                helper that ended without one.
            LauncherError: The launcher refused (a process survived, a tree is not empty).
        """
        try:
            async with asyncio.timeout(timeout_seconds):
                _, descriptors = await self._call(
                    protocol.RemovePlugin(plugin=plugin, uid=uid), expect=1
                )
                data = await read_pipe(descriptors[0], MAX_RESULT_BYTES)
        except TimeoutError:
            raise LauncherUnavailableError(
                f"the launcher did not finish removing {plugin} within {timeout_seconds:.0f} s"
            ) from None
        try:
            outcome = json.loads(data)
        except ValueError:
            raise LauncherUnavailableError(
                f"the launcher's removal of {plugin} ended without an outcome"
            ) from None
        if not outcome.get("ok"):
            raise LauncherError(outcome.get("error") or f"the launcher could not remove {plugin}")

    async def _call(self, request, descriptors: list[int] = (), *, expect: int = 0):
        async with self._lock:
            if self._socket is None:
                await self._connect_locked()
            try:
                await self._send(protocol.encode_request(request), list(descriptors))
                packet, received = await self._receive()
            except (asyncio.CancelledError, LauncherError):
                # The launcher may still answer the request just sent; drop the connection so
                # a later call never reads that answer as its own. The next call reconnects.
                self._drop_connection()
                raise
        response = json.loads(packet)
        if not response.get("ok"):
            for descriptor in received:
                os.close(descriptor)
            error = response.get("error", "the launcher refused the request")
            if response.get("temporary"):
                raise LauncherUnavailableError(error)
            raise LauncherError(error)
        if len(received) != expect:
            for descriptor in received:
                os.close(descriptor)
            raise LauncherError(f"the launcher sent {len(received)} descriptor(s), not {expect}")
        return response["result"], received

    async def _send(self, packet: bytes, descriptors: list[int]) -> None:
        while True:
            try:
                if descriptors:
                    socket.send_fds(self._socket, [packet], descriptors)
                else:
                    self._socket.send(packet)
                return
            except BlockingIOError:
                await self._wait(writable=True)
            except OSError as error:
                raise LauncherUnavailableError(f"the launcher connection failed: {error}") from None

    async def _receive(self) -> tuple[bytes, list[int]]:
        while True:
            try:
                packet, descriptors, _, _ = socket.recv_fds(
                    self._socket,
                    protocol.MAX_MESSAGE_BYTES,
                    protocol.MAX_DESCRIPTORS,
                    socket.MSG_CMSG_CLOEXEC,
                )
            except BlockingIOError:
                await self._wait(writable=False)
                continue
            except OSError as error:
                raise LauncherUnavailableError(f"the launcher connection failed: {error}") from None
            if not packet:
                raise LauncherUnavailableError("the launcher closed the connection")
            return packet, descriptors

    async def _wait(self, *, writable: bool) -> None:
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        descriptor = self._socket.fileno()
        if writable:
            loop.add_writer(descriptor, ready.set_result, None)
        else:
            loop.add_reader(descriptor, ready.set_result, None)
        try:
            await ready
        finally:
            if writable:
                loop.remove_writer(descriptor)
            else:
                loop.remove_reader(descriptor)
