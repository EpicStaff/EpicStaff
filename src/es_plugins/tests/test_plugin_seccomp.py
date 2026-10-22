"""The seccomp filter plugin processes run under: no System V IPC object, made or opened."""

import errno
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from es_plugins.launcher.plugin_seccomp import (
    ARCHITECTURES,
    SECCOMP_RET_ALLOW,
    SECCOMP_RET_ERRNO,
    plugin_filter,
)


def statements(program: bytes) -> list[tuple[int, int, int, int]]:
    return [struct.unpack("<HBBI", program[index : index + 8]) for index in range(0, len(program), 8)]


@pytest.mark.parametrize("machine", sorted(ARCHITECTURES))
def test_the_filter_refuses_another_abi_and_the_three_calls_and_allows_the_rest(machine):
    program = statements(plugin_filter(machine))
    architecture = ARCHITECTURES[machine]
    refuse = SECCOMP_RET_ERRNO | errno.EPERM

    assert program[0] == (0x20, 0, 0, 4)  # the architecture
    assert program[1] == (0x15, 1, 0, architecture.audit_arch)
    assert program[2] == (0x06, 0, 0, refuse)
    assert program[3] == (0x20, 0, 0, 0)  # the system call number
    checks = program[4:-2]
    assert [value for _, _, _, value in checks if value in architecture.refused] == list(architecture.refused)
    # Every check jumps to the final refusal; nothing else does.
    for offset, (_, jump_true, _, _) in enumerate(checks):
        assert 4 + offset + 1 + jump_true == len(program) - 1
    assert program[-2] == (0x06, 0, 0, SECCOMP_RET_ALLOW)
    assert program[-1] == (0x06, 0, 0, refuse)


def test_an_unknown_architecture_has_no_filter():
    with pytest.raises(ValueError, match="no plugin seccomp filter is known for riscv64"):
        plugin_filter("riscv64")


# Makes one object of each kind (and removes what it made); prints each call's id or -errno.
SYSTEM_V_AND_OTHERS = """
import ctypes, json, os
libc = ctypes.CDLL(None, use_errno=True)
results = []
for make, remove in (
    (lambda: libc.shmget(0, 4096, 0o1600), lambda made: libc.shmctl(made, 0, None)),
    (lambda: libc.msgget(0, 0o1600), lambda made: libc.msgctl(made, 0, None)),
    (lambda: libc.semget(0, 1, 0o1600), lambda made: libc.semctl(made, 0, 0)),
):
    made = make()
    results.append(-ctypes.get_errno() if made < 0 else made)
    if made >= 0:
        remove(made)
results.append(os.getpid() > 0)
print(json.dumps(results))
"""


@pytest.mark.root
def test_a_spawned_plugin_process_cannot_make_system_v_ipc_objects(layout, tmp_path):
    from es_plugins.launcher.process_spawn import SpawnSpec, spawn_process

    output = tmp_path / "output"
    descriptor = open(output, "wb")
    try:
        pid = spawn_process(
            SpawnSpec(
                uid=20031,
                gid=20031,
                argv=[sys.executable, "-I", "-c", SYSTEM_V_AND_OTHERS],
                environment={"PATH": "/usr/bin:/bin"},
                working_directory=Path("/"),
                output_descriptor=descriptor.fileno(),
                seccomp_filter=plugin_filter(),
            )
        )
    finally:
        descriptor.close()
    import os

    os.waitpid(pid, 0)
    assert json.loads(output.read_text()) == [-errno.EPERM, -errno.EPERM, -errno.EPERM, True]


@pytest.mark.root
def test_without_the_filter_the_same_calls_work():
    completed = subprocess.run([sys.executable, "-I", "-c", SYSTEM_V_AND_OTHERS], capture_output=True, text=True, check=True)

    shm, msg, sem, _ = json.loads(completed.stdout)
    assert shm >= 0 and msg >= 0 and sem >= 0
