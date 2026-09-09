"""ctypes binding to the Linux Landlock LSM (kernel 5.13+).

Landlock lets a process irreversibly restrict *itself* to an allowlist of
filesystem paths. Unlike chroot or bubblewrap it needs no capabilities, so it
works inside this container's `cap_drop: ALL` profile, and the restriction is
enforced by the kernel on the syscall path -- it cannot be undone or bypassed
from user space by `ctypes`, raw `open()`, or a `subprocess` re-exec.

No third-party dependency: the syscalls (`landlock_create_ruleset`,
`landlock_add_rule`, `landlock_restrict_self`) have no libc wrapper, so they
are invoked directly via `ctypes.CDLL(None).syscall()`. Numbers below are the
x86_64 syscall table; this module only supports that architecture.
"""

import ctypes
import os
from collections.abc import Iterable

_libc = ctypes.CDLL(None, use_errno=True)

_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446

_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1

_PR_SET_NO_NEW_PRIVS = 38

# --- LANDLOCK_ACCESS_FS_* bit flags, in ABI-introduction order ------------
_EXECUTE = 1 << 0
_WRITE_FILE = 1 << 1
_READ_FILE = 1 << 2
_READ_DIR = 1 << 3
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE_CHAR = 1 << 6
_MAKE_DIR = 1 << 7
_MAKE_REG = 1 << 8
_MAKE_SOCK = 1 << 9
_MAKE_FIFO = 1 << 10
_MAKE_BLOCK = 1 << 11
_MAKE_SYM = 1 << 12
_REFER = 1 << 13
_TRUNCATE = 1 << 14
_IOCTL_DEV = 1 << 15

# Highest access-right bit each ABI version knows about. A ruleset must not
# request bits its kernel doesn't support, or landlock_create_ruleset() fails
# with EINVAL.
_ABI_ACCESS_FS_MASK = {
    1: 0x1FFF,
    2: 0x3FFF,
    3: 0x7FFF,
    4: 0x7FFF,
}
_LATEST_KNOWN_ACCESS_FS_MASK = 0xFFFF

# Rights that only apply to directories. Attaching one of these to a rule
# whose target is a regular file makes landlock_add_rule() fail with EINVAL,
# so they must be masked off per-rule based on the target's type.
_DIRECTORY_ONLY_ACCESS_FS = (
    _READ_DIR
    | _REMOVE_DIR
    | _REMOVE_FILE
    | _MAKE_CHAR
    | _MAKE_DIR
    | _MAKE_REG
    | _MAKE_SOCK
    | _MAKE_FIFO
    | _MAKE_BLOCK
    | _MAKE_SYM
    | _REFER
)

_READ_ONLY_ACCESS_FS = _READ_FILE | _READ_DIR
_READ_EXEC_ACCESS_FS = _READ_FILE | _READ_DIR | _EXECUTE
_READ_WRITE_ACCESS_FS = (
    _READ_FILE
    | _READ_DIR
    | _WRITE_FILE
    | _TRUNCATE
    | _REMOVE_DIR
    | _REMOVE_FILE
    | _MAKE_DIR
    | _MAKE_REG
    | _MAKE_SYM
    | _MAKE_FIFO
    | _MAKE_SOCK
    | _REFER
)


class LandlockUnavailableError(RuntimeError):
    """Raised when the running kernel does not support Landlock at all."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _access_fs_mask(abi: int) -> int:
    return _ABI_ACCESS_FS_MASK.get(abi, _LATEST_KNOWN_ACCESS_FS_MASK)


def _raise_on_syscall_error(return_value: int, description: str) -> int:
    if return_value < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"{description} failed: {os.strerror(errno)}")
    return return_value


def abi_version() -> int:
    """The kernel's Landlock ABI version, or 0 when Landlock is unsupported.

    Queries via landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
    -- the documented way to probe support without creating a ruleset.
    """
    result = _libc.syscall(
        ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
        None,
        ctypes.c_size_t(0),
        ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    return result if result > 0 else 0


def _add_rule(ruleset_fd: int, path: str, access_fs: int) -> None:
    path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        rule = _PathBeneathAttr(allowed_access=access_fs, parent_fd=path_fd)
        _raise_on_syscall_error(
            _libc.syscall(
                ctypes.c_long(_SYS_LANDLOCK_ADD_RULE),
                ctypes.c_int(ruleset_fd),
                ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
                ctypes.byref(rule),
                ctypes.c_uint32(0),
            ),
            f"landlock_add_rule({path})",
        )
    finally:
        os.close(path_fd)


def apply(
    rw_paths: Iterable[str],
    ro_paths: Iterable[str],
    roexec_paths: Iterable[str],
) -> None:
    """Irreversibly confine this process, and every descendant of it, to the
    given paths. `rw_paths` get full read/write/create/delete access,
    `ro_paths` get read-only access, `roexec_paths` get read + execute
    access. Paths that don't exist on disk are skipped rather than failing
    the whole call -- the allowlists this is fed are intentionally generous
    across environments that may not have every entry.

    Every access right the running kernel's ABI knows about is handled (i.e.
    denied unless a rule below grants it back). Handling only the rights this
    jail happens to use would leave every other right -- e.g. IOCTL_DEV,
    MAKE_CHAR -- completely unrestricted for every path on the filesystem,
    defeating the point of an allowlist.
    """
    abi = abi_version()
    if abi < 1:
        raise LandlockUnavailableError(
            "Landlock is not supported by this kernel; cannot sandbox the "
            "execution."
        )

    access_fs_mask = _access_fs_mask(abi)
    ruleset_attr = _RulesetAttr(handled_access_fs=access_fs_mask)
    ruleset_fd = _raise_on_syscall_error(
        _libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
            ctypes.byref(ruleset_attr),
            ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
            ctypes.c_uint32(0),
        ),
        "landlock_create_ruleset",
    )
    try:
        path_groups = (
            (rw_paths, _READ_WRITE_ACCESS_FS),
            (ro_paths, _READ_ONLY_ACCESS_FS),
            (roexec_paths, _READ_EXEC_ACCESS_FS),
        )
        for paths, group_access_fs in path_groups:
            for path in paths:
                # Skipping a missing allowlist entry is intentional (see the
                # apply() docstring) -- it must not log. This module runs
                # inside the captured execution subprocess: anything written
                # to stdout/stderr here lands in CodeResultData and is shown
                # to the user or handed to the LLM as the tool observation.
                if not os.path.exists(path):
                    continue
                access_fs = group_access_fs & access_fs_mask
                if not os.path.isdir(path):
                    access_fs &= ~_DIRECTORY_ONLY_ACCESS_FS
                _add_rule(ruleset_fd, path, access_fs)

        _raise_on_syscall_error(
            _libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0),
            "prctl(PR_SET_NO_NEW_PRIVS)",
        )
        _raise_on_syscall_error(
            _libc.syscall(
                ctypes.c_long(_SYS_LANDLOCK_RESTRICT_SELF),
                ctypes.c_int(ruleset_fd),
                ctypes.c_uint32(0),
            ),
            "landlock_restrict_self",
        )
    finally:
        os.close(ruleset_fd)
