"""Signal every process of a plugin UID, from a helper that takes that UID.

The launcher holds no `CAP_KILL`, so it cannot signal a plugin's processes itself. A helper
forked from it takes the plugin's UID as its effective one and calls `kill(-1, sig)`, which
reaches every process whose real or saved UID is the helper's real or effective one: the
plugin's processes, including children that called `setsid` or were reparented to PID 1.
`killpg` as root is never used.

Its real and saved UID are `SIGNALLER_UID`, which no plugin and nothing else on the node has, so
the plugin cannot signal the helper back (stop it before it sends, say). Its `kill(-1)` also
reaches processes of `SIGNALLER_UID`: only other signalling helpers.

The other helpers (`run_as_user`: purge, IPC clean-up) take the UID whole, so a process of it
could stop them; they run only once a kill has left none. The launcher answers one request at a
time, so it still never waits for any helper past a deadline, nor at all once it is stopped: it
reports the helper as not finished and goes on. The helper stays its child, and the next
`kill_uid` round, whose `kill(-1, SIGKILL)` reaches every process of the UID, ends it; the
launcher's loop then reaps it.
"""

import contextlib
import os
import select
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass

from es_plugins.layout import AGENT_UID
from es_plugins.process_table import ProcessTable
from es_plugins.uid_range import UidRange

KILL_TIMEOUT_SECONDS = 10.0
# Below every PLUGINS_NODE_UID_RANGE (`UidRange.MINIMUM_FIRST`), and not the agent's.
SIGNALLER_UID = 9999
# A signalling helper switches user and makes one system call: it is done within milliseconds
# unless stopped. The deadline bounds what one such helper can cost the launcher's loop.
SIGNAL_SECONDS = 2.0
_PAUSE_BETWEEN_ROUNDS_SECONDS = 0.05
# How often a helper that has not exited is checked for being stopped: a pidfd shows an exit only.
_STOP_CHECK_SECONDS = 0.02


@dataclass(frozen=True)
class KillOutcome:
    rounds: int
    remaining: tuple[int, ...]
    """Pids of the UID still alive when the timeout passed; empty on success."""


def switch_to_user(uid: int, gid: int) -> None:
    """Drop every group and switch the real, effective and saved IDs, in that order."""
    os.setgroups([])
    os.setresgid(gid, gid, gid)
    os.setresuid(uid, uid, uid)


def check_signaller_uid(uid_range: UidRange) -> None:
    """Refuse a node where `SIGNALLER_UID` is a plugin's UID or the agent's.

    Raises:
        ValueError: It is: a plugin could stop the signalling helper again, or every helper's
            `kill(-1)` would reach the agent too.
    """
    if SIGNALLER_UID in uid_range or SIGNALLER_UID == AGENT_UID:
        raise ValueError(
            f"the launcher's signalling UID {SIGNALLER_UID} must be outside "
            "PLUGINS_NODE_UID_RANGE and not the agent's"
        )


def _switch_to_signaller(uid: int) -> None:
    os.setgroups([])
    os.setresgid(SIGNALLER_UID, SIGNALLER_UID, SIGNALLER_UID)
    os.setresuid(SIGNALLER_UID, uid, SIGNALLER_UID)


def run_as_user(uid: int, action: Callable[[], None], *, timeout_seconds: float) -> bool:
    """Run `action` in a forked helper as `uid` (gid = uid); return whether it succeeded.

    False also when the helper did not exit within `timeout_seconds`, or was stopped: it is
    then left running, or stopped, for a later kill of the UID (see the module docstring).
    The helper never returns into the caller's code: it leaves with `os._exit`.
    """
    return _run_in_helper(lambda: switch_to_user(uid, uid), action, timeout_seconds)


def _run_in_helper(
    switch: Callable[[], None], action: Callable[[], None], timeout_seconds: float
) -> bool:
    helper = os.fork()
    if helper == 0:
        status = 1
        try:
            switch()
            action()
            status = 0
        except BaseException:
            status = 1
        finally:
            os._exit(status)
    return _wait_for_helper(helper, time.monotonic() + timeout_seconds)


def _wait_for_helper(helper: int, deadline: float) -> bool:
    exited = os.pidfd_open(helper)
    try:
        poller = select.poll()
        poller.register(exited, select.POLLIN)
        while True:
            pid, wait_status = os.waitpid(helper, os.WNOHANG | os.WUNTRACED)
            if pid:
                return (
                    not os.WIFSTOPPED(wait_status) and os.waitstatus_to_exitcode(wait_status) == 0
                )
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            poller.poll(min(left, _STOP_CHECK_SECONDS) * 1000)
    finally:
        os.close(exited)


def signal_uid(uid: int, signal_number: int, *, timeout_seconds: float = SIGNAL_SECONDS) -> bool:
    """Send one signal to every process of `uid`; return whether the helper finished.

    `kill(-1)` fails with ESRCH when the UID has no process; that is not an error here.
    """

    def send() -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(-1, signal_number)

    return _run_in_helper(lambda: _switch_to_signaller(uid), send, timeout_seconds)


def kill_uid(
    uid: int,
    process_table: ProcessTable,
    *,
    reap: Callable[[], None] = lambda: None,
    timeout_seconds: float = KILL_TIMEOUT_SECONDS,
) -> KillOutcome:
    """SIGKILL every process of `uid` until none is left, or the timeout passes.

    One round usually suffices; another is needed when a process forked between the
    helper's `kill` and its own exit. `reap` collects the caller's exited children, so a
    killed child of the launcher does not linger as a zombie.

    The first round is unconditional: a process the table cannot see as living is still
    signalled, so none is missed because of how the table reads its state.
    """
    deadline = time.monotonic() + timeout_seconds
    rounds = 0
    while (rounds == 0 or process_table.living_pids_of_uid(uid)) and (
        left := deadline - time.monotonic()
    ) > 0:
        rounds += 1
        signal_uid(uid, signal.SIGKILL, timeout_seconds=min(SIGNAL_SECONDS, left))
        time.sleep(_PAUSE_BETWEEN_ROUNDS_SECONDS)
        reap()
    return KillOutcome(rounds=rounds, remaining=tuple(process_table.living_pids_of_uid(uid)))
