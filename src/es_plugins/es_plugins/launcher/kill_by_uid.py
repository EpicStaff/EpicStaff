"""Signal every process of a plugin UID, from a helper that runs as that UID.

The launcher holds no `CAP_KILL`, so it cannot signal a plugin's processes itself. A helper
forked from it switches to the plugin's UID and calls `kill(-1, sig)`, which reaches every
process that UID may signal: its own processes, including children that called `setsid` or
were reparented to PID 1, and nothing of any other UID. `killpg` as root is never used.
"""

import contextlib
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass

from es_plugins.process_table import ProcessTable

KILL_TIMEOUT_SECONDS = 10.0
_PAUSE_BETWEEN_ROUNDS_SECONDS = 0.05


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


def run_as_user(uid: int, action: Callable[[], None]) -> bool:
    """Run `action` in a forked helper as `uid` (gid = uid); return whether it succeeded.

    The helper never returns into the caller's code: it leaves with `os._exit`.
    """
    helper = os.fork()
    if helper == 0:
        status = 1
        try:
            switch_to_user(uid, uid)
            action()
            status = 0
        except BaseException:
            status = 1
        finally:
            os._exit(status)
    _, wait_status = os.waitpid(helper, 0)
    return os.waitstatus_to_exitcode(wait_status) == 0


def signal_uid(uid: int, signal_number: int) -> None:
    """Send one signal to every process of `uid`.

    `kill(-1)` fails with ESRCH when the UID has no process; that is not an error here.
    """

    def send() -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(-1, signal_number)

    run_as_user(uid, send)


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
    """
    deadline = time.monotonic() + timeout_seconds
    rounds = 0
    while process_table.living_pids_of_uid(uid) and time.monotonic() < deadline:
        rounds += 1
        signal_uid(uid, signal.SIGKILL)
        time.sleep(_PAUSE_BETWEEN_ROUNDS_SECONDS)
        reap()
    return KillOutcome(rounds=rounds, remaining=tuple(process_table.living_pids_of_uid(uid)))
