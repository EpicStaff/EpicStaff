"""Run one plugin's process: start it, watch it, restart it with backoff, stop it.

The launcher starts the process and is its parent; the agent watches it through the pidfd the
launcher sends back, which becomes readable when the process exits. The agent holds every port
of the node's range (see `PortReservation`) and hands the placement's listening socket to each
process at spawn as file descriptor 3, so the process serves on a port it never binds.

Health is `GET /_epicstaff/health` on the plugin's port: every second until the first answer
(for at most a minute), then every 15 s; three failures in a row count as a stop. An
unexpected stop (exit, failed health, over memory) kills whatever is left of the UID and
restarts after the `RestartPolicy` backoff, or leaves the plugin `failed`. A plugin over its
disk cap is killed and left `failed` at once (`fail_for`): a restart would only fill the disk
again. A deliberate stop sends SIGTERM, waits up to the grace period, then SIGKILL.
"""

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from es_plugins.agent.launcher_client import LauncherClient, LauncherError, SpawnedProcess
from es_plugins.health.health_checker import HealthChecker
from es_plugins.logs.log_collector import LogCollector
from es_plugins.supervisor.restart_policy import STABLE_AFTER_SECONDS, RestartPolicy

STARTUP_PROBE_INTERVAL_SECONDS = 1.0
STARTUP_GRACE_SECONDS = 60.0
HEALTH_INTERVAL_SECONDS = 15.0
HEALTH_FAILURES_BEFORE_RESTART = 3
STOP_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to start the plugin's process once."""

    plugin: str
    uid: int
    version: str
    argv: list[str]
    environment: dict[str, str]
    nice: int
    port: int
    memory_mb: int


@dataclass(frozen=True)
class ProcessStatus:
    observed_state: str
    health: str
    pid: int | None
    restarts: int
    rss_mb: float | None
    last_error: str | None
    version: str | None


class _ProcessStopError(Exception):
    """Ends one run of the process; the message is the reason the node reports."""


class ProcessSupervisor:
    def __init__(
        self,
        plugin: str,
        uid: int,
        launcher: LauncherClient,
        health_checker: HealthChecker,
        log_collector: LogCollector,
        on_change: Callable[[], None],
        *,
        listen_fd: int | None = None,
        policy: RestartPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.plugin = plugin
        self.uid = uid
        self._launcher = launcher
        self._health_checker = health_checker
        self._log_collector = log_collector
        self._on_change = on_change
        self._listen_fd = listen_fd
        self._policy = policy or RestartPolicy()
        self._clock = clock
        self._lock = asyncio.Lock()
        self._spec: ProcessSpec | None = None
        self._run_task: asyncio.Task | None = None
        # Wakes the run task: for a deliberate stop (`_stopping`) or to restart for a reason.
        self._interrupt = asyncio.Event()
        self._interrupt_reason: str | None = None
        self._stopping = False
        # Set by `fail_for`: the run ends `failed` with this error instead of restarting.
        self._give_up_reason: str | None = None
        # "unknown" until the first action: a new placement is neither running nor deliberately
        # stopped. `stop()` sets "stopped" explicitly.
        self._observed_state = "unknown"
        self._health = "unknown"
        self._pid: int | None = None
        self._rss_mb: float | None = None
        self._last_error: str | None = None
        # How many processes this supervisor has started; numbers each one (`running_process`).
        self._started_processes = 0

    @property
    def spec(self) -> ProcessSpec | None:
        return self._spec

    @property
    def failed(self) -> bool:
        return self._observed_state == "failed"

    @property
    def watching(self) -> bool:
        """True while a process runs or is about to be restarted."""
        return self._run_task is not None and not self._run_task.done()

    @property
    def memory_mb(self) -> int | None:
        return self._spec.memory_mb if self._spec else None

    def status(self) -> ProcessStatus:
        # rss_mb is None, not 0.0, while nothing runs: the node reports "not measured".
        running = self.watching and self._observed_state not in ("failed", "stopped")
        return ProcessStatus(
            observed_state=self._observed_state,
            health=self._health,
            pid=self._pid,
            restarts=self._policy.restarts,
            rss_mb=self._rss_mb if running else None,
            last_error=self._last_error,
            version=self._spec.version if self._spec else None,
        )

    def running_process(self) -> int | None:
        """The running process's number; None while none runs or it is being stopped.

        Each process the supervisor starts gets the next number, so a caller that saw one number
        and later sees None or another number knows the process it talked to is gone. The
        number turns None before a stop or restart signals the process, so a caller whose
        connection to the process broke already sees it.
        """
        if self._pid is None or self._stopping or self._interrupt.is_set():
            return None
        return self._started_processes

    def record_memory(self, rss_mb: float | None) -> None:
        self._rss_mb = rss_mb

    def set_listen_fd(self, listen_fd: int) -> None:
        """The agent's held listening socket; handed to each process at spawn as its fd 3."""
        self._listen_fd = listen_fd

    async def start(self, spec: ProcessSpec) -> None:
        """Start the process deliberately (first start, or a restart EpicStaff asked for)."""
        async with self._lock:
            await self._stop_current()
            self._spec = spec
            self._policy.reset()
            self._last_error = None
            self._interrupt.clear()
            self._interrupt_reason = None
            self._give_up_reason = None
            self._run_task = asyncio.create_task(self._run(), name=f"supervise-{self.plugin}")

    async def stop(self) -> None:
        """Stop the process deliberately; it stays stopped until `start`."""
        async with self._lock:
            await self._stop_current()
            self._set_state("stopped", "unknown")

    def restart_for_memory(self, rss_mb: float) -> None:
        """The UID uses more memory than its cap: kill it and restart with backoff."""
        self._interrupt_for(
            f"used {rss_mb:.1f} MB, more than its memory limit of {self._spec.memory_mb} MB"
        )

    def fail_for(self, reason: str) -> None:
        """Kill the UID and leave the plugin `failed` with `reason`, without a restart.

        Also during a backoff, when no process runs. It stays failed until the next `start`.
        """
        if not self.watching or self._stopping or self._give_up_reason is not None:
            return
        self._give_up_reason = reason
        self._interrupt_reason = reason
        self._interrupt.set()

    def _interrupt_for(self, reason: str) -> None:
        # Only while a process runs: during a backoff there is nothing to kill.
        if self._pid is None or self._stopping or self._interrupt.is_set():
            return
        self._interrupt_reason = reason
        self._interrupt.set()

    def show_phase(self, observed_state: str) -> None:
        """Report a step before the process exists (`downloading`, `building`)."""
        self._set_state(observed_state, "unknown")

    def fail(self, error: str) -> None:
        """Mark the plugin failed without a process (e.g. its package could not be installed)."""
        self._last_error = error
        self._set_state("failed", "unknown")

    def note_error(self, error: str | None) -> None:
        self._last_error = error
        self._on_change()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._run_once()
                return
            except _ProcessStopError as stop:
                reason = str(stop)
            except Exception as error:
                # Supervision must go on: an error of the node's own is one more stop.
                logger.exception("Supervising plugin {} failed", self.plugin)
                reason = f"internal error of the node agent: {error}"
                self._pid = None
            if self._stopping:
                return
            if self._give_up():
                return
            self._interrupt.clear()
            self._interrupt_reason = None
            self._last_error = reason
            logger.warning("Plugin {} stopped: {}", self.plugin, reason)
            delay = self._policy.next_delay()
            if delay is None:
                logger.error("Plugin {} failed: too many restarts", self.plugin)
                self._set_state("failed", "unknown")
                return
            # "starting", not "failed": EpicStaff marks the plugin failed only when it gives up.
            # on_change here carries last_error for this abnormal stop (log_tail stays
            # failed-only, set by the controller).
            self._set_state("starting", "failing")
            # A deliberate stop, or `fail_for`, ends the backoff at once instead of waiting it out.
            await _first_of(self._interrupt, timeout=delay)
            if self._give_up():
                return

    def _give_up(self) -> bool:
        """End in `failed` if `fail_for` asked for it; return whether it did."""
        if self._give_up_reason is None:
            return False
        logger.error("Plugin {} failed: {}", self.plugin, self._give_up_reason)
        self._last_error = self._give_up_reason
        self._set_state("failed", "unknown")
        return True

    async def _run_once(self) -> None:
        spec = self._spec
        self._set_state("starting", "unknown")
        process, output = await self._spawn(spec)
        collector = asyncio.create_task(self._log_collector.collect(output))
        exited = _readable_event(process.pidfd)
        try:
            await self._watch(spec, process, exited)
        finally:
            await self._terminate(process, exited)
            _stop_watching(process.pidfd)
            os.close(process.pidfd)
            self._pid = None
            self._rss_mb = None
            # The collector ends once the pipe's last writer is gone, i.e. after the kill.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(collector, STOP_GRACE_SECONDS)

    async def _terminate(self, process: SpawnedProcess, exited: asyncio.Event) -> None:
        """Bring the process down: SIGTERM then a grace period for a deliberate stop, else kill."""
        if exited.is_set():
            # Already gone; mop up any children it left (reparented to the launcher).
            await self._kill_uid()
            return
        if self._stopping:
            # A deliberate stop: let the process finish in-flight work before SIGKILL.
            try:
                await self._launcher.terminate_uid(self.uid)
            except LauncherError as error:
                logger.warning("Could not ask plugin {} to stop: {}", self.plugin, error)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(exited.wait(), STOP_GRACE_SECONDS)
        await self._kill_uid()

    async def _spawn(self, spec: ProcessSpec) -> tuple[SpawnedProcess, int]:
        """Start the process; return it and the read end of its output pipe."""
        if self._listen_fd is None:
            raise _ProcessStopError("its listening socket was not bound")
        try:
            await self._launcher.prepare_plugin(spec.plugin, spec.uid)
        except LauncherError as error:
            raise _ProcessStopError(f"its directories could not be prepared: {error}") from None
        read_end, write_end = os.pipe()
        try:
            process = await self._launcher.spawn(
                spec.plugin,
                spec.uid,
                spec.argv,
                spec.environment,
                spec.nice,
                write_end,
                self._listen_fd,
            )
        except LauncherError as error:
            os.close(read_end)
            raise _ProcessStopError(f"it could not be started: {error}") from None
        finally:
            os.close(write_end)
        self._pid = process.pid
        self._started_processes += 1
        logger.info(
            "Started plugin {} {} as UID {} (pid {})",
            spec.plugin,
            spec.version,
            spec.uid,
            process.pid,
        )
        self._on_change()
        return process, read_end

    async def _watch(
        self, spec: ProcessSpec, process: SpawnedProcess, exited: asyncio.Event
    ) -> None:
        started = self._clock()
        healthy_since: float | None = None
        failures = 0
        while True:
            interval = (
                STARTUP_PROBE_INTERVAL_SECONDS if healthy_since is None else HEALTH_INTERVAL_SECONDS
            )
            await _first_of(exited, self._interrupt, timeout=interval)
            # The interrupt first: a deliberate stop sets it before the process is signalled.
            if self._interrupt.is_set():
                if self._stopping:
                    return
                raise _ProcessStopError(self._interrupt_reason)
            if exited.is_set():
                raise _ProcessStopError(await self._exit_reason(process.pid))
            if await self._health_checker.is_healthy(spec.port):
                failures = 0
                now = self._clock()
                if healthy_since is None:
                    healthy_since = now
                    self._set_state("running", "ok")
                elif self._health != "ok":
                    self._set_state("running", "ok")
                if now - healthy_since >= STABLE_AFTER_SECONDS:
                    self._policy.mark_stable()
                continue
            if healthy_since is None:
                if self._clock() - started > STARTUP_GRACE_SECONDS:
                    raise _ProcessStopError(
                        f"it did not answer its health check within {STARTUP_GRACE_SECONDS:.0f} s"
                    )
                continue
            failures += 1
            self._set_state("running", "failing")
            if failures >= HEALTH_FAILURES_BEFORE_RESTART:
                raise _ProcessStopError(f"it failed {failures} health checks in a row")

    async def _exit_reason(self, pid: int) -> str:
        try:
            status = await self._launcher.exit_status(pid)
        except LauncherError:
            status = None
        if status is None:
            return "its process exited"
        if status < 0:
            try:
                name = signal.Signals(-status).name
            except ValueError:
                name = f"signal {-status}"  # a real-time signal has no Signals member
            return f"its process was killed by {name}"
        return f"its process exited with status {status}"

    async def _stop_current(self) -> None:
        if not self.watching:
            return
        # A deliberate stop: the run task's `_terminate` is graceful and nothing restarts.
        self._stopping = True
        self._interrupt.set()
        try:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._run_task), STOP_GRACE_SECONDS + 2)
            if not self._run_task.done():
                self._run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._run_task
                await self._kill_uid()
        finally:
            self._stopping = False
        self._run_task = None
        self._pid = None
        self._rss_mb = None

    async def _kill_uid(self) -> None:
        try:
            remaining = await self._launcher.kill_uid(self.uid)
        except LauncherError as error:
            logger.error("Could not kill the processes of plugin {}: {}", self.plugin, error)
            return
        if remaining:
            logger.error("Plugin {} still has processes {} after the kill", self.plugin, remaining)

    def _set_state(self, observed_state: str, health: str) -> None:
        if (observed_state, health) != (self._observed_state, self._health):
            self._observed_state = observed_state
            self._health = health
            self._on_change()


def _readable_event(descriptor: int) -> asyncio.Event:
    event = asyncio.Event()
    asyncio.get_running_loop().add_reader(descriptor, event.set)
    return event


def _stop_watching(descriptor: int) -> None:
    asyncio.get_running_loop().remove_reader(descriptor)


async def _first_of(*events: asyncio.Event, timeout: float) -> None:
    waiters = [asyncio.create_task(event.wait()) for event in events]
    try:
        await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
