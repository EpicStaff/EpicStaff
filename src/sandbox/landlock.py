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

Besides filesystem paths, this module can optionally restrict outbound TCP
connections to a fixed set of ports (Landlock ABI 4+, kernel 6.7+). This
control is **TCP-only and port-granular**: Landlock net has no notion of IP
address or hostname -- it cannot express "only connect to host X" -- and it
does not cover UDP at all, so UDP traffic (including DNS resolution) is
completely unrestricted by it regardless of what is passed to `apply()`.
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
_LANDLOCK_RULE_NET_PORT = 2

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

# --- LANDLOCK_ACCESS_NET_* bit flags, introduced in ABI 4 ----------------
_LANDLOCK_ACCESS_NET_BIND_TCP = 1 << 0
_LANDLOCK_ACCESS_NET_CONNECT_TCP = 1 << 1

_MIN_ABI_FOR_NET = 4

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


class LandlockNetworkUnavailableError(RuntimeError):
    """Raised when TCP-port restriction is requested but the running kernel's
    Landlock ABI (< 4) cannot enforce it. Callers must not treat this as
    "no network restriction requested" and silently proceed unconfined --
    that would fail open on exactly the executions that asked to be
    confined."""


class _RulesetAttr(ctypes.Structure):
    # Both fields must always be declared: the size passed to
    # landlock_create_ruleset() must match how many of these fields are
    # actually populated (see apply()), and the kernel validates that size
    # exactly. A struct that only ever declares handled_access_fs would make
    # it impossible to opt into the net field at a later ctypes.sizeof() call.
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


# Explicit sizes rather than ctypes.sizeof(): the kernel's EINVAL check on
# landlock_create_ruleset()'s size argument is exactly what would regress if
# a struct-size computation crept in a compiler-dependent extra byte.
_RULESET_ATTR_SIZE_FS_ONLY = 8
_RULESET_ATTR_SIZE_FS_AND_NET = 16


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _NetPortAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("port", ctypes.c_uint64)]


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
    return max(0, result)


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


def _add_net_rule(ruleset_fd: int, port: int, allowed_access: int) -> None:
    rule = _NetPortAttr(allowed_access=allowed_access, port=port)
    _raise_on_syscall_error(
        _libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_ADD_RULE),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(_LANDLOCK_RULE_NET_PORT),
            ctypes.byref(rule),
            ctypes.c_uint32(0),
        ),
        f"landlock_add_rule(tcp port {port})",
    )


def apply(
    rw_paths: Iterable[str],
    ro_paths: Iterable[str],
    roexec_paths: Iterable[str],
    *,
    allowed_tcp_ports: tuple[int, ...] | None = None,
) -> None:
    """Irreversibly confine this process, and every descendant of it, to the
    given paths. `rw_paths` get full read/write/create/delete access,
    `ro_paths` get read-only access, `roexec_paths` get read + execute
    access. Missing paths are skipped rather than failing the call.

    `allowed_tcp_ports`: `None` leaves net rights untouched (existing callers
    unaffected). A tuple grants `CONNECT_TCP` to exactly those ports and
    denies it elsewhere -- an empty tuple deliberately means "deny all TCP
    connect", not a no-op. On Landlock ABI < 4, raises
    `LandlockNetworkUnavailableError` rather than failing open.

    Landlock network control is TCP-only and port-granular: it has no
    IP/hostname dimension and no UDP coverage at all -- DNS and other UDP
    traffic are unrestricted regardless of this parameter.
    """
    abi = abi_version()
    if abi < 1:
        raise LandlockUnavailableError(
            "Landlock is not supported by this kernel; cannot sandbox the execution."
        )

    handle_net = allowed_tcp_ports is not None
    if handle_net and abi < _MIN_ABI_FOR_NET:
        raise LandlockNetworkUnavailableError(
            f"Landlock ABI {abi} does not support network restriction "
            f"(requires ABI {_MIN_ABI_FOR_NET}+, kernel 6.7+); refusing to "
            "silently run without the requested TCP-port confinement."
        )

    access_fs_mask = _access_fs_mask(abi)
    if handle_net:
        ruleset_attr = _RulesetAttr(
            handled_access_fs=access_fs_mask,
            handled_access_net=(_LANDLOCK_ACCESS_NET_BIND_TCP | _LANDLOCK_ACCESS_NET_CONNECT_TCP),
        )
        ruleset_attr_size = _RULESET_ATTR_SIZE_FS_AND_NET
    else:
        ruleset_attr = _RulesetAttr(handled_access_fs=access_fs_mask)
        ruleset_attr_size = _RULESET_ATTR_SIZE_FS_ONLY

    ruleset_fd = _raise_on_syscall_error(
        _libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
            ctypes.byref(ruleset_attr),
            ctypes.c_size_t(ruleset_attr_size),
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

        if handle_net:
            for port in allowed_tcp_ports:
                _add_net_rule(ruleset_fd, port, _LANDLOCK_ACCESS_NET_CONNECT_TCP)

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
