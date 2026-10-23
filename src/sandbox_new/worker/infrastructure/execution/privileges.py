"""Dropping the execution subprocess from root to ``sandboxuser``.

On kernels without Landlock signal isolation (ABI < 6) this uid drop is the only
thing stopping an execution from signalling the supervisor. It is a no-op when the
worker is not running as root (local dev / CI), which is logged once at startup.
"""

import os
import pwd

from loguru import logger

__all__ = [
    "SANDBOX_GID",
    "SANDBOX_UID",
    "can_drop_privileges",
    "privilege_drop_kwargs",
    "warn_if_unprivileged",
]

try:
    _SANDBOX_PW = pwd.getpwnam("sandboxuser")
    SANDBOX_UID: int = _SANDBOX_PW.pw_uid
    SANDBOX_GID: int = _SANDBOX_PW.pw_gid
except KeyError:
    SANDBOX_UID = 1000
    SANDBOX_GID = 1000


def can_drop_privileges() -> bool:
    """Return True only when the current process is root."""
    return os.geteuid() == 0


def privilege_drop_kwargs() -> dict[str, object]:
    """Subprocess kwargs to run a child as sandboxuser, or empty when non-root."""
    if not can_drop_privileges():
        return {}
    return {"user": SANDBOX_UID, "group": SANDBOX_GID, "extra_groups": []}


def warn_if_unprivileged() -> None:
    """Warn once when privilege drop is disabled because the worker is non-root."""
    if not can_drop_privileges():
        logger.warning(
            "Worker is running as non-root (uid={}); subprocess privilege drop is "
            "DISABLED. This is expected in local dev/CI but a security risk in "
            "production.",
            os.geteuid(),
        )
