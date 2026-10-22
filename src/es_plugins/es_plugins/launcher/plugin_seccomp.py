"""The seccomp filter every plugin process runs under: no System V IPC object, and no io_uring.

System V shared memory, message queues and semaphores live in the container's IPC namespace,
which every plugin shares, and outlive the process that made them: one plugin could pass data to
another through them, or hand one to another plugin's UID and keep it attached so that plugin's
removal could never delete it. A plugin needs none of them. So `shmget`, `msgget` and `semget`
answer EPERM, and so does every system call of another ABI than the node's own (32-bit and x32
calls, which reach the same objects through other numbers).

`io_uring_setup`, `io_uring_enter` and `io_uring_register` answer EPERM too: io_uring runs
socket operations (socket, connect, bind, listen) in the kernel on a process's behalf, where no
seccomp filter sees them, and a plugin's Python needs none of it. Docker's own default profile
refuses them only from some versions on; this filter does whatever Docker the host runs.

It is a classic BPF program of a dozen instructions, built here for the node's architecture, so
no seccomp library is needed. The spawn sequence installs it after `PR_SET_NO_NEW_PRIVS`, the one
condition the kernel sets for an unprivileged process to install a filter, and the process and
everything it starts keep it: a filter can be added to, never removed.
"""

import ctypes
import errno
import os
import platform
import struct
from typing import NamedTuple

PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000
# struct seccomp_data: int nr at offset 0, __u32 arch at offset 4.
_NR_OFFSET, _ARCH_OFFSET = 0, 4
_LOAD_WORD, _JUMP_IF_EQUAL, _JUMP_IF_AT_LEAST, _RETURN = 0x20, 0x15, 0x35, 0x06
_X32_SYSCALL_BIT = 0x40000000


class _Architecture(NamedTuple):
    audit_arch: int
    refused: tuple[int, ...]
    has_x32: bool


# io_uring_setup, io_uring_enter and io_uring_register: the same numbers on both architectures.
_IO_URING = (425, 426, 427)
# The audit architecture of each ABI, and its numbers for shmget, msgget and semget, then io_uring.
ARCHITECTURES = {
    "x86_64": _Architecture(0xC000003E, (29, 68, 64, *_IO_URING), has_x32=True),
    "aarch64": _Architecture(0xC00000B7, (194, 186, 190, *_IO_URING), has_x32=False),
}


def _statement(code: int, jump_true: int, jump_false: int, value: int) -> bytes:
    return struct.pack("<HBBI", code, jump_true, jump_false, value)


def plugin_filter(machine: str | None = None) -> bytes:
    """The filter's instructions (`struct sock_filter` each) for `machine` (the node's own).

    Raises:
        ValueError: No filter is known for that architecture.
    """
    name = machine or platform.machine()
    architecture = ARCHITECTURES.get(name)
    if architecture is None:
        raise ValueError(f"no plugin seccomp filter is known for {name}")
    refuse = SECCOMP_RET_ERRNO | errno.EPERM
    checks = []
    if architecture.has_x32:
        checks.append((_JUMP_IF_AT_LEAST, _X32_SYSCALL_BIT))
    checks += [(_JUMP_IF_EQUAL, number) for number in architecture.refused]
    program = [
        _statement(_LOAD_WORD, 0, 0, _ARCH_OFFSET),
        # Another ABI: refused. The node's own: go on to the system call number.
        _statement(_JUMP_IF_EQUAL, 1, 0, architecture.audit_arch),
        _statement(_RETURN, 0, 0, refuse),
        _statement(_LOAD_WORD, 0, 0, _NR_OFFSET),
    ]
    for index, (code, value) in enumerate(checks):
        # Each check jumps over the checks after it and the "allow" to the final "refuse".
        program.append(_statement(code, len(checks) - index, 0, value))
    program.append(_statement(_RETURN, 0, 0, SECCOMP_RET_ALLOW))
    program.append(_statement(_RETURN, 0, 0, refuse))
    return b"".join(program)


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def install_filter(program: bytes) -> None:
    """Install `program` for this process and everything it starts. Needs `no_new_privs`.

    Raises:
        OSError: The kernel refused the filter.
    """
    instructions = ctypes.create_string_buffer(program, len(program))
    descriptor = _SockFprog(len(program) // 8, ctypes.addressof(instructions))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(descriptor), 0, 0) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
