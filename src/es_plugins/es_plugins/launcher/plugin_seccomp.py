"""The seccomp filter every plugin process runs under, whatever profile Docker gives the container.

- **No System V IPC object.** System V shared memory, message queues and semaphores live in the
  container's IPC namespace, which every plugin shares, and outlive the process that made them:
  one plugin could pass data to another through them, or hand one to another plugin's UID and
  keep it attached so that plugin's removal could never delete it. A plugin needs none of them.
  So `shmget`, `msgget` and `semget` answer EPERM.
- **No io_uring.** `io_uring_setup`, `io_uring_enter` and `io_uring_register` answer EPERM:
  io_uring runs socket operations (socket, connect, bind, listen) in the kernel on a process's
  behalf, where no seccomp filter sees them.
- **No namespaces.** `unshare` and `setns` answer EPERM, and so does `clone` with any namespace
  flag (`CLONE_NEWNS`, `NEWUTS`, `NEWIPC`, `NEWUSER`, `NEWPID`, `NEWNET`, `NEWCGROUP`): a new user
  namespace would give the plugin capabilities over namespaces of its own, and the kernel code
  they reach. `clone3` answers ENOSYS, as in Docker's default profile: its flags are behind a
  pointer, which a filter cannot read, and glibc falls back to `clone` on ENOSYS, so threads
  and child processes still work.
- **No kernel keyring, BPF, perf events or userfaultfd.** `keyctl`, `add_key`, `request_key`,
  `bpf`, `perf_event_open` and `userfaultfd` answer EPERM: kernel interfaces a web backend does
  not use, with a long history of privilege escalations.
- **No other ABI.** Every system call of another ABI than the node's own (32-bit and x32
  calls, which reach the same objects through other numbers) answers EPERM.

Docker's default profile refuses most of these too, but only from some versions on, only without
some capabilities, and only when the host runs it; this filter does whatever the host runs.

It is a classic BPF program of a few dozen instructions, built here for the node's architecture,
so no seccomp library is needed. The spawn sequence installs it after `PR_SET_NO_NEW_PRIVS`, the
one condition the kernel sets for an unprivileged process to install a filter, and the process
and everything it starts keep it: a filter can be added to, never removed.
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
REFUSED = SECCOMP_RET_ERRNO | errno.EPERM
NOT_IMPLEMENTED = SECCOMP_RET_ERRNO | errno.ENOSYS
# struct seccomp_data: int nr at offset 0, __u32 arch at 4, __u64 instruction_pointer at 8, then
# __u64 args[6] from 16. The low half of args[0] is at 16 on both little-endian architectures.
_NR_OFFSET, _ARCH_OFFSET, _FIRST_ARGUMENT_LOW_OFFSET = 0, 4, 16
LOAD_WORD, JUMP_IF_EQUAL, JUMP_IF_AT_LEAST, JUMP_IF_ANY_BIT, RETURN = 0x20, 0x15, 0x35, 0x45, 0x06
_X32_SYSCALL_BIT = 0x40000000
# CLONE_NEWNS, CLONE_NEWCGROUP, CLONE_NEWUTS, CLONE_NEWIPC, CLONE_NEWUSER, CLONE_NEWPID and
# CLONE_NEWNET (include/uapi/linux/sched.h). The kernel reads only the low 32 bits of clone's flags.
CLONE_NAMESPACE_FLAGS = (
    0x00020000 | 0x02000000 | 0x04000000 | 0x08000000 | 0x10000000 | 0x20000000 | 0x40000000
)


class SystemCalls(NamedTuple):
    """The numbers the filter names on one architecture (`arch/*/entry/syscalls`, asm-generic)."""

    refused: dict[str, int]
    """Answered EPERM, whatever their arguments."""

    clone: int
    """Refused with a namespace flag in its first argument, allowed otherwise."""

    clone3: int
    """Answered ENOSYS."""


class _Architecture(NamedTuple):
    audit_arch: int
    system_calls: SystemCalls
    has_x32: bool


# The same numbers on both architectures: io_uring (425-427) and clone3 (435).
_IO_URING = {"io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427}
ARCHITECTURES = {
    "x86_64": _Architecture(
        0xC000003E,
        SystemCalls(
            refused={
                "shmget": 29,
                "semget": 64,
                "msgget": 68,
                **_IO_URING,
                "unshare": 272,
                "setns": 308,
                "add_key": 248,
                "request_key": 249,
                "keyctl": 250,
                "bpf": 321,
                "perf_event_open": 298,
                "userfaultfd": 323,
            },
            clone=56,
            clone3=435,
        ),
        has_x32=True,
    ),
    "aarch64": _Architecture(
        0xC00000B7,
        SystemCalls(
            refused={
                "msgget": 186,
                "semget": 190,
                "shmget": 194,
                **_IO_URING,
                "unshare": 97,
                "setns": 268,
                "add_key": 217,
                "request_key": 218,
                "keyctl": 219,
                "bpf": 280,
                "perf_event_open": 241,
                "userfaultfd": 282,
            },
            clone=220,
            clone3=435,
        ),
        has_x32=False,
    ),
}


class _Jump(NamedTuple):
    """A conditional jump to a label, resolved once the program is laid out."""

    code: int
    value: int
    when_true: str
    when_false: str | None = None
    """None: the next instruction."""


class _Label(NamedTuple):
    """Where the next instruction is, for a jump to name."""

    name: str


def plugin_filter(machine: str | None = None) -> bytes:
    """The filter's instructions (`struct sock_filter` each) for `machine` (the node's own).

    Raises:
        ValueError: No filter is known for that architecture.
    """
    name = machine or platform.machine()
    architecture = ARCHITECTURES.get(name)
    if architecture is None:
        raise ValueError(f"no plugin seccomp filter is known for {name}")
    calls = architecture.system_calls
    checks: list = [
        (LOAD_WORD, _ARCH_OFFSET),
        # Another ABI: refused. The node's own: go on to the system call number.
        _Jump(JUMP_IF_EQUAL, architecture.audit_arch, "number", "refuse"),
        _Label("number"),
        (LOAD_WORD, _NR_OFFSET),
    ]
    if architecture.has_x32:
        checks.append(_Jump(JUMP_IF_AT_LEAST, _X32_SYSCALL_BIT, "refuse"))
    checks += [_Jump(JUMP_IF_EQUAL, number, "refuse") for number in calls.refused.values()]
    checks += [
        _Jump(JUMP_IF_EQUAL, calls.clone3, "not implemented"),
        _Jump(JUMP_IF_EQUAL, calls.clone, "clone"),
        (RETURN, SECCOMP_RET_ALLOW),
        _Label("clone"),
        (LOAD_WORD, _FIRST_ARGUMENT_LOW_OFFSET),
        _Jump(JUMP_IF_ANY_BIT, CLONE_NAMESPACE_FLAGS, "refuse"),
        (RETURN, SECCOMP_RET_ALLOW),
        _Label("not implemented"),
        (RETURN, NOT_IMPLEMENTED),
        _Label("refuse"),
        (RETURN, REFUSED),
    ]
    return _assemble(checks)


def _assemble(items: list) -> bytes:
    """Lay out the instructions and resolve each jump to its label (BPF jumps only forward)."""
    labels: dict[str, int] = {}
    instructions = []
    for item in items:
        if isinstance(item, _Label):
            labels[item.name] = len(instructions)
        else:
            instructions.append(item)
    program = []
    for index, instruction in enumerate(instructions):
        if isinstance(instruction, _Jump):
            when_true = labels[instruction.when_true] - index - 1
            when_false = (
                0 if instruction.when_false is None else labels[instruction.when_false] - index - 1
            )
            program.append(_statement(instruction.code, when_true, when_false, instruction.value))
        else:
            code, value = instruction
            program.append(_statement(code, 0, 0, value))
    return b"".join(program)


def _statement(code: int, jump_true: int, jump_false: int, value: int) -> bytes:
    return struct.pack("<HBBI", code, jump_true, jump_false, value)


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
