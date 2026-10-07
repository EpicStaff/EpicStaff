"""ctypes binding to libseccomp (`libseccomp.so.2`), already present in the
sandbox base image -- no new dependency.

Denies `socket(2)` for anything other than AF_UNIX, so the sandboxed process
and every descendant of it can no longer open an IP socket, even across
`execve` (the filter is a kernel-side, inherited restriction).

Naming hazard: never `import seccomp` here -- this module is named
`seccomp.py`, so that would shadow itself on `sys.path`. The C library is
loaded by soname instead; `ctypes.util.find_library` is avoided too since it
shells out to binutils, which the slim base image doesn't have.
"""

import ctypes
import errno as errno_module
import socket

_libseccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
_libc = ctypes.CDLL(None, use_errno=True)

_PR_SET_NO_NEW_PRIVS = 38

_SCMP_ACT_ALLOW = 0x7FFF0000  # seccomp_init() default action: allow unmatched syscalls
_SCMP_ACT_KILL_PROCESS = 0x80000000  # action: kill the whole process, not just the thread

_SCMP_ACT_ERRNO_BASE = 0x00050000  # libseccomp action bits for "return an errno"
_SCMP_ACT_ERRNO_MASK = 0xFFFF  # low 16 bits carry the errno value itself


def _scmp_act_errno(errno_value: int) -> int:
    return _SCMP_ACT_ERRNO_BASE | (errno_value & _SCMP_ACT_ERRNO_MASK)


_SCMP_CMP_NE = 1  # seccomp_rule_add_array() comparison op: "not equal"

# seccomp_attr_set() attribute identifiers.
_SCMP_FLTATR_ACT_BADARCH = 2  # action to take for a syscall from an unknown/foreign ABI
_SCMP_FLTATR_CTL_TSYNC = 4  # apply the filter to every thread in the process, not just this one

_AF_UNIX = socket.AF_UNIX

_EACCES = errno_module.EACCES


class SeccompUnavailableError(RuntimeError):
    """Raised when the running kernel/libseccomp refuse to install the filter."""


class _ScmpArgCmp(ctypes.Structure):
    """Mirrors libseccomp's `struct scmp_arg_cmp` (arg index, comparison op,
    and up to two comparison operands)."""

    _fields_ = [
        ("arg", ctypes.c_uint32),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


# ctypes can't read C headers, so every function used below needs its
# restype/argtypes declared explicitly; a wrong restype on a pointer-returning
# function (seccomp_init) would silently truncate the pointer on 64-bit.
_libseccomp.seccomp_init.restype = ctypes.c_void_p  # -> scmp_filter_ctx (opaque pointer)
_libseccomp.seccomp_init.argtypes = [ctypes.c_uint32]  # (default_action)
_libseccomp.seccomp_release.argtypes = [ctypes.c_void_p]  # (ctx)
_libseccomp.seccomp_release.restype = None
_libseccomp.seccomp_load.argtypes = [ctypes.c_void_p]  # (ctx)
_libseccomp.seccomp_attr_set.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_uint32,
]  # (ctx, attr, value)
_libseccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]  # (syscall_name)
_libseccomp.seccomp_syscall_resolve_name.restype = (
    ctypes.c_int
)  # -> syscall number, or negative on error
_libseccomp.seccomp_rule_add_array.argtypes = [
    ctypes.c_void_p,  # ctx
    ctypes.c_uint32,  # action
    ctypes.c_int,  # syscall number
    ctypes.c_uint,  # arg_cnt
    ctypes.POINTER(_ScmpArgCmp),  # arg_array
]

# Below, seccomp_rule_add_array() is used deliberately instead of
# seccomp_rule_add(): the latter is a varargs function taking scmp_arg_cmp
# structs *by value*, which ctypes cannot express reliably across
# architectures/ABIs. seccomp_rule_add_array() takes a pointer to an array
# instead, which is a normal, safely-declarable ctypes signature.


def _resolve_syscall(name: bytes) -> int:
    syscall_number = _libseccomp.seccomp_syscall_resolve_name(name)
    if syscall_number < 0:
        raise SeccompUnavailableError(
            f"seccomp_syscall_resolve_name({name.decode()!r}) failed: "
            f"unknown syscall on this architecture"
        )
    return syscall_number


def block_network() -> None:
    """Irreversibly block IP networking for this process and every
    descendant of it, including across `execve`.

    Sets PR_SET_NO_NEW_PRIVS itself before installing the filter -- a
    one-way kernel latch, so calling this alongside landlock.apply() (which
    also sets it) in either order is a harmless no-op the second time.
    """
    if _libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        prctl_errno = ctypes.get_errno()
        raise SeccompUnavailableError(f"prctl(PR_SET_NO_NEW_PRIVS) failed: errno {prctl_errno}")

    ctx = _libseccomp.seccomp_init(_SCMP_ACT_ALLOW)
    if not ctx:
        raise SeccompUnavailableError("seccomp_init() failed")

    try:
        # KILL_PROCESS on BADARCH closes the x32 ABI path: x32 uses different
        # syscall numbers, so a process reaching the kernel through it would
        # otherwise bypass the syscall-number checks below.
        result = _libseccomp.seccomp_attr_set(ctx, _SCMP_FLTATR_ACT_BADARCH, _SCMP_ACT_KILL_PROCESS)
        if result != 0:
            raise SeccompUnavailableError(f"seccomp_attr_set(BADARCH) failed: {result}")

        # TSYNC, not prctl(PR_SET_SECCOMP): the latter installs the filter on
        # the calling thread only, leaving other threads (and their spawns)
        # unrestricted. TSYNC applies to the whole thread group atomically.
        result = _libseccomp.seccomp_attr_set(ctx, _SCMP_FLTATR_CTL_TSYNC, 1)
        if result != 0:
            raise SeccompUnavailableError(f"seccomp_attr_set(TSYNC) failed: {result}")

        deny_eacces = _scmp_act_errno(_EACCES)

        # socket(2) -- deny every family except AF_UNIX, with EACCES rather
        # than KILL, so the child gets a normal PermissionError instead of
        # dying on SIGSYS. AF_UNIX stays open since it's not an egress path
        # (multiprocessing, logging handlers, local IPC depend on it).
        socket_family_conditions = (_ScmpArgCmp * 1)(
            _ScmpArgCmp(arg=0, op=_SCMP_CMP_NE, datum_a=_AF_UNIX, datum_b=0)
        )
        result = _libseccomp.seccomp_rule_add_array(
            ctx,
            deny_eacces,
            _resolve_syscall(b"socket"),
            1,
            socket_family_conditions,
        )
        if result != 0:
            raise SeccompUnavailableError(f"seccomp_rule_add_array(socket) failed: {result}")

        # io_uring bypasses seccomp entirely -- it can drive sockets through
        # ring submission/completion queues without going through socket(2),
        # so denying these three syscalls is required, not defense-in-depth.
        for syscall_name in (b"io_uring_setup", b"io_uring_enter", b"io_uring_register"):
            result = _libseccomp.seccomp_rule_add_array(
                ctx, deny_eacces, _resolve_syscall(syscall_name), 0, None
            )
            if result != 0:
                raise SeccompUnavailableError(
                    f"seccomp_rule_add_array({syscall_name.decode()}) failed: {result}"
                )

        result = _libseccomp.seccomp_load(ctx)
        if result != 0:
            raise SeccompUnavailableError(f"seccomp_load() failed: {result}")
    finally:
        # seccomp_load() succeeding does not mean the ctx should leak --
        # release it on every path, including failures.
        _libseccomp.seccomp_release(ctx)
