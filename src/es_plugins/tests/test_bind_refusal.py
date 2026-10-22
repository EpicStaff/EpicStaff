"""Refusing inet bind() to plugin UIDs with a cgroup BPF program."""

import errno
import os
import socket
import struct

import pytest

from es_plugins.bind_refusal import refusal_program
from es_plugins.uid_range import UidRange

# A range no other test runs a process as: the attachment stays with the test container's cgroup.
REFUSED = UidRange(29000, 29009)


def has_cap_bpf() -> bool:
    with open("/proc/self/status") as status:
        effective = next(int(line.split()[1], 16) for line in status if line.startswith("CapEff"))
    return bool(effective & (1 << 39))


def test_the_program_refuses_the_range_and_allows_every_other_uid():
    program = refusal_program(REFUSED)

    instructions = [struct.unpack("<BBhi", program[index : index + 8]) for index in range(0, len(program), 8)]
    assert len(instructions) == 8
    assert instructions[0] == (0x85, 0, 0, 15)  # bpf_get_current_uid_gid
    assert instructions[2] == (0xA5, 0, 3, 29000) and instructions[3] == (0x25, 0, 2, 29009)
    assert instructions[4] == (0xB7, 0, 0, 0) and instructions[6] == (0xB7, 0, 0, 1)


def bind_as(uid: int) -> int:
    """0 when a TCP bind to port 0 works as `uid`, else its errno."""
    read_end, write_end = os.pipe()
    child = os.fork()
    if child == 0:
        result = 255
        try:
            os.setgroups([])
            os.setresgid(uid, uid, uid)
            os.setresuid(uid, uid, uid)
            with socket.socket() as probe:
                probe.bind(("0.0.0.0", 0))
            result = 0
        except OSError as error:
            result = error.errno
        finally:
            os.write(write_end, bytes([result]))
            os._exit(0)
    os.close(write_end)
    result = os.read(read_end, 1)[0]
    os.close(read_end)
    os.waitpid(child, 0)
    return result


@pytest.mark.root
@pytest.mark.skipif(not os.path.exists("/proc/self/status") or not has_cap_bpf(), reason="needs CAP_BPF (the entrypoint's)")
def test_once_installed_a_plugin_uid_cannot_bind_and_any_other_can():
    from es_plugins.bind_refusal import install_bind_refusal

    install_bind_refusal(REFUSED)

    assert bind_as(REFUSED.first) == errno.EPERM
    assert bind_as(REFUSED.last) == errno.EPERM
    assert bind_as(REFUSED.last + 1) == 0
    assert bind_as(10000) == 0
