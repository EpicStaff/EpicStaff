"""Refuse `bind()` of an inet socket to every plugin UID: a cgroup BPF program, set at start-up.

A plugin serves on the listening socket the agent hands it as fd 3, and never needs to bind one.
A bound socket holds one of the network namespace's ephemeral ports before any packet is sent,
so the connection limits of `network_limits` never see it; refusing the bind, TCP and UDP alike,
closes that way of taking ports.

What it cannot refuse: the kernel binds a port by itself, without `bind()` and so without this
hook, for `listen()` on an unbound TCP socket and for `connect()` (TCP or UDP). Connected TCP
sockets are what the connection limits count; a listening socket of a plugin UID, or more inet
sockets than a plugin needs, are what the agent's socket watchdog stops
(`supervisor.socket_watchdog`).

The program is the kernel's `BPF_PROG_TYPE_CGROUP_SOCK_ADDR` for `bind()` of IPv4 and IPv6
sockets, attached to the container's own cgroup (cgroup v2, which Docker gives each container):
the calling process's UID in `PLUGINS_NODE_UID_RANGE` makes `bind()` fail with EPERM; any other
UID (the agent, the launcher) binds as before. It is eight instructions, assembled here, so the
node needs no BPF library. Loading it needs CAP_BPF and CAP_NET_ADMIN, which only the entrypoint
holds; an attachment stays with the cgroup, and nothing on the node afterwards can detach it.

After attaching, a child running as the first plugin UID tries a TCP and a UDP bind, on IPv4
and IPv6: one that succeeds is an error, and the node does not start (fail closed, like the
connection limits).
"""

import ctypes
import errno
import os
import platform
import socket
import struct
from pathlib import Path

from es_plugins.uid_range import UidRange

CGROUP_ROOT = Path("/sys/fs/cgroup")
_BPF_SYSCALL = {"x86_64": 321, "aarch64": 280}
_BPF_PROG_LOAD, _BPF_PROG_ATTACH = 5, 8
_BPF_PROG_TYPE_CGROUP_SOCK_ADDR = 18
_BPF_CGROUP_INET4_BIND, _BPF_CGROUP_INET6_BIND = 8, 9
_BPF_F_ALLOW_MULTI = 2
_BPF_FUNC_GET_CURRENT_UID_GID = 15
_ATTRIBUTE_BYTES = 128
_LOG_BYTES = 65536
# What the start-up check tries as a plugin UID: TCP and UDP, IPv4 and IPv6, any port.
_PROBES = tuple(
    (family, kind, address)
    for family, address in ((socket.AF_INET, ("0.0.0.0", 0)), (socket.AF_INET6, ("::", 0)))
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM)
)


class BindRefusalError(Exception):
    """The refusal could not be set, or a plugin UID can still bind; the message says which."""


def _instruction(
    code: int, destination: int = 0, source: int = 0, offset: int = 0, immediate: int = 0
) -> bytes:
    return struct.pack("<BBhi", code, (source << 4) | destination, offset, immediate)


def refusal_program(uid_range: UidRange) -> bytes:
    """The program: return 0 (refuse) for a UID in `uid_range`, 1 (allow) for any other."""
    return b"".join(
        [
            _instruction(0x85, immediate=_BPF_FUNC_GET_CURRENT_UID_GID),  # r0 = uid and gid
            _instruction(0xBC, destination=0, source=0),  # w0 = w0: the uid, upper half cleared
            _instruction(
                0xA5, destination=0, offset=3, immediate=uid_range.first
            ),  # uid < first: allow
            _instruction(
                0x25, destination=0, offset=2, immediate=uid_range.last
            ),  # uid > last: allow
            _instruction(0xB7, destination=0, immediate=0),  # r0 = 0: refuse
            _instruction(0x95),  # exit
            _instruction(0xB7, destination=0, immediate=1),  # r0 = 1: allow
            _instruction(0x95),  # exit
        ]
    )


def install_bind_refusal(
    uid_range: UidRange, *, cgroup: Path = CGROUP_ROOT, probe_uid: int | None = None
) -> None:
    """Attach the refusal for IPv4 and IPv6 binds, then check a plugin UID is refused.

    `probe_uid` is the plugin UID the check runs as (the range's first by default); the caller
    is root with CAP_SETUID.

    Raises:
        BindRefusalError: The kernel refused the program (no CAP_BPF, no cgroup v2), or a plugin
            UID can still bind afterwards.
    """
    syscall_number = _BPF_SYSCALL.get(platform.machine())
    if syscall_number is None:
        raise BindRefusalError(f"no bpf() system call number is known for {platform.machine()}")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    program = refusal_program(uid_range)
    try:
        group = os.open(cgroup, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as error:
        raise BindRefusalError(
            f"the container's cgroup {cgroup} cannot be opened: {error}"
        ) from None
    try:
        for attach_type in (_BPF_CGROUP_INET4_BIND, _BPF_CGROUP_INET6_BIND):
            loaded = _load(libc, syscall_number, program, attach_type)
            try:
                _bpf(
                    libc,
                    syscall_number,
                    _BPF_PROG_ATTACH,
                    struct.pack("<IIII", group, loaded, attach_type, _BPF_F_ALLOW_MULTI),
                    "attaching the bind refusal to the container's cgroup",
                )
            finally:
                # The attachment keeps the program; this descriptor is no longer needed.
                os.close(loaded)
    finally:
        os.close(group)
    refused = _bind_as(uid_range.first if probe_uid is None else probe_uid)
    if refused is not True:
        raise BindRefusalError(f"a plugin UID can still bind an inet socket: {refused}")


def _load(libc, syscall_number: int, program: bytes, attach_type: int) -> int:
    instructions = ctypes.create_string_buffer(program, len(program))
    license_text = ctypes.create_string_buffer(b"GPL")
    log = ctypes.create_string_buffer(_LOG_BYTES)
    attribute = struct.pack(
        "<IIQQIIQII16sII",
        _BPF_PROG_TYPE_CGROUP_SOCK_ADDR,
        len(program) // 8,
        ctypes.addressof(instructions),
        ctypes.addressof(license_text),
        1,
        _LOG_BYTES,
        ctypes.addressof(log),
        0,
        0,
        b"plugin_bind",
        0,
        attach_type,
    )
    try:
        return _bpf(libc, syscall_number, _BPF_PROG_LOAD, attribute, "loading the bind refusal")
    except BindRefusalError as error:
        detail = log.value.decode(errors="replace").strip()
        raise BindRefusalError(f"{error}{f' ({detail[-300:]})' if detail else ''}") from None


def _bpf(libc, syscall_number: int, command: int, attribute: bytes, step: str) -> int:
    buffer = ctypes.create_string_buffer(attribute, _ATTRIBUTE_BYTES)
    result = libc.syscall(syscall_number, command, buffer, _ATTRIBUTE_BYTES)
    if result < 0:
        number = ctypes.get_errno()
        raise BindRefusalError(
            f"{step} failed: {os.strerror(number)} (is CAP_BPF given, and cgroup v2?)"
        )
    return result


def _bind_as(uid: int) -> bool | str:
    """In a child running as `uid`: True when every inet bind (TCP and UDP) is refused, else
    what was bound."""
    read_end, write_end = os.pipe2(os.O_CLOEXEC)
    child = os.fork()
    if child == 0:
        outcome = "the check could not run"
        try:
            os.close(read_end)
            os.setgroups([])
            os.setresgid(uid, uid, uid)
            os.setresuid(uid, uid, uid)
            outcome = "refused"
            for family, kind, address in _PROBES:
                try:
                    probe = socket.socket(family, kind)
                except OSError:
                    continue  # no IPv6 in this namespace: nothing to bind there
                try:
                    probe.bind(address)
                    outcome = f"bound {family.name} {kind.name} port {probe.getsockname()[1]}"
                    break
                except OSError as error:
                    if error.errno != errno.EPERM:
                        outcome = f"{family.name} {kind.name} bind failed otherwise: {error}"
                        break
                finally:
                    probe.close()
        finally:
            os.write(write_end, outcome.encode())
            os._exit(0)
    os.close(write_end)
    try:
        outcome = os.read(read_end, 512).decode()
    finally:
        os.close(read_end)
        os.waitpid(child, 0)
    return True if outcome == "refused" else outcome
