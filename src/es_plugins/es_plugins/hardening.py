"""Process-wide hardening the launcher and the agent apply to themselves at start-up."""

import ctypes

PR_SET_DUMPABLE = 4

_libc = ctypes.CDLL(None, use_errno=True)


def make_not_dumpable() -> None:
    """Clear the dumpable flag, so a process of the same UID cannot read this one or trace it.

    With it cleared the kernel owns `/proc/<pid>` as root and denies `/proc/<pid>/environ`,
    `/proc/<pid>/mem` and `ptrace` to everyone but root. Defence in depth: a plugin runs as a
    different UID and cannot reach the agent anyway, but this holds even if one ever shared it.
    `execve` resets the flag, so the agent's own subprocesses (pip, venv) are unaffected.
    """
    if _libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, "prctl(PR_SET_DUMPABLE, 0) failed")
