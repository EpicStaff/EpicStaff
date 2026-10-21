"""Start a process as another UID: the launcher's one privileged spawn sequence.

In the child, before `execve`, in this order:

1. `setsid`: its own session and process group.
2. stdin from `/dev/null`; stdout and stderr to the given descriptor; the agent's listening
   socket, when given, placed at file descriptor 3 and left inheritable, so the plugin serves
   on a port only the agent could bind.
3. Resource limits, while still root. The kernel decides at the moment of `setresuid`,
   against the limit in force then, whether `execve` checks `RLIMIT_NPROC`; set afterwards,
   the launcher's own (unlimited) limit would apply at the switch and the process would
   start however many the UID already runs.
4. Niceness and `oom_score_adj`: raising either needs no privilege, and a high
   `oom_score_adj` makes the kernel kill a plugin rather than the agent or the launcher.
5. `setgroups([])`, `setresgid`, `setresuid`: from here on the process has no capability.
6. `PR_SET_NO_NEW_PRIVS`, so no file it executes can regain one.
7. Working directory, close every other descriptor, `execve` with exactly the given
   environment.

A failure in the child is written to a close-on-exec pipe, so the caller gets the reason
instead of a process that silently exited with 127.
"""

import ctypes
import fcntl
import os
import resource
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PR_SET_NO_NEW_PRIVS = 38
CHILD_FAILURE_EXIT_CODE = 127
# The plugin's listening socket is handed to it here; epicstaff_plugin.serve reads this fd.
LISTEN_FD = 3
# Python ignores these; an ignored signal stays ignored across execve.
_SIGNALS_TO_RESTORE = (signal.SIGPIPE, signal.SIGXFSZ)

_libc = ctypes.CDLL(None, use_errno=True)


class SpawnError(Exception):
    """The process could not be started; the message says which step failed."""


@dataclass(frozen=True)
class SpawnSpec:
    uid: int
    gid: int
    argv: Sequence[str]
    environment: Mapping[str, str]
    working_directory: Path
    nice: int = 0
    resource_limits: Sequence[tuple[int, int]] = ()
    oom_score_adj: int | None = None
    output_descriptor: int | None = None
    """Becomes stdout and stderr; None keeps the caller's."""

    listen_descriptor: int | None = None
    """The agent's listening socket; becomes the child's fd 3 (inheritable) when given."""


def spawn_process(spec: SpawnSpec) -> int:
    """Fork and exec `spec`; return the child's pid once `execve` has succeeded.

    Raises:
        SpawnError: A step in the child failed; the child has exited and been reaped.
    """
    error_read, error_write = os.pipe2(os.O_CLOEXEC)
    if error_write <= LISTEN_FD:
        # The child overwrites fds 0 to 3; the error pipe must not be one of them.
        moved = fcntl.fcntl(error_write, fcntl.F_DUPFD_CLOEXEC, LISTEN_FD + 1)
        os.close(error_write)
        error_write = moved
    pid = os.fork()
    if pid == 0:
        os.close(error_read)
        _become_child(spec, error_write)
    os.close(error_write)
    error = b""
    while chunk := os.read(error_read, 4096):
        error += chunk
    os.close(error_read)
    if error:
        os.waitpid(pid, 0)
        raise SpawnError(error.decode(errors="replace"))
    return pid


def _become_child(spec: SpawnSpec, error_write: int) -> None:
    step = "setsid"
    try:
        os.setsid()
        step = "standard streams"
        null_input = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null_input, 0)
        if spec.output_descriptor is not None:
            os.dup2(spec.output_descriptor, 1)
            os.dup2(spec.output_descriptor, 2)
        step = "listen socket"
        if spec.listen_descriptor is not None:
            # The error pipe is above fd 3 (see `spawn_process`), so fd 3 is free to take the
            # listening socket; dup2 clears close-on-exec, so the plugin inherits it.
            if spec.listen_descriptor != LISTEN_FD:
                os.dup2(spec.listen_descriptor, LISTEN_FD)
            else:
                os.set_inheritable(LISTEN_FD, True)
        step = "resource limits"
        for limit, value in spec.resource_limits:
            resource.setrlimit(limit, (value, value))
        step = "niceness"
        os.setpriority(os.PRIO_PROCESS, 0, spec.nice)
        if spec.oom_score_adj is not None:
            step = "oom_score_adj"
            with open("/proc/self/oom_score_adj", "w", encoding="ascii") as adjustment:
                adjustment.write(str(spec.oom_score_adj))
        step = "signal dispositions"
        for signal_number in _SIGNALS_TO_RESTORE:
            signal.signal(signal_number, signal.SIG_DFL)
        step = "user switch"
        os.setgroups([])
        os.setresgid(spec.gid, spec.gid, spec.gid)
        os.setresuid(spec.uid, spec.uid, spec.uid)
        step = "no_new_privs"
        if _libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
        step = "working directory"
        os.chdir(spec.working_directory)
        step = "execve"
        maximum_descriptor = os.sysconf("SC_OPEN_MAX")
        # Keep 0,1,2, the listening socket at fd 3 (when given), and error_write (CLOEXEC, so
        # it closes on a successful execve); close everything else the child inherited.
        lowest_kept = LISTEN_FD if spec.listen_descriptor is not None else 2
        os.closerange(lowest_kept + 1, error_write)
        os.closerange(error_write + 1, maximum_descriptor)
        os.execve(spec.argv[0], list(spec.argv), dict(spec.environment))
    except BaseException as error:
        try:
            os.write(error_write, f"{step}: {type(error).__name__}: {error}".encode())
        finally:
            os._exit(CHILD_FAILURE_EXIT_CODE)
