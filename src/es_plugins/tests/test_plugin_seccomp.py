"""The seccomp filter plugin processes run under: no System V IPC object, io_uring, namespace, kernel
keyring, BPF, perf event or userfaultfd; `clone3` answers ENOSYS, and Python still works."""

import errno
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from es_plugins.launcher.plugin_seccomp import (
    ARCHITECTURES,
    CLONE_NAMESPACE_FLAGS,
    JUMP_IF_ANY_BIT,
    JUMP_IF_AT_LEAST,
    JUMP_IF_EQUAL,
    LOAD_WORD,
    NOT_IMPLEMENTED,
    REFUSED,
    RETURN,
    SECCOMP_RET_ALLOW,
    plugin_filter,
)
from tests.helpers import SYSTEM_PYTHON

ES_PLUGINS = Path(__file__).resolve().parents[1]

# The kernel's numbers, from arch/x86/entry/syscalls/syscall_64.tbl and
# include/uapi/asm-generic/unistd.h (aarch64).
KERNEL_NUMBERS = {
    "x86_64": {
        "shmget": 29, "semget": 64, "msgget": 68, "io_uring_setup": 425, "io_uring_enter": 426,
        "io_uring_register": 427, "unshare": 272, "setns": 308, "add_key": 248, "request_key": 249,
        "keyctl": 250, "bpf": 321, "perf_event_open": 298, "userfaultfd": 323, "clone": 56, "clone3": 435,
        "read": 0, "write": 1, "vfork": 58, "exit_group": 231,
    },
    "aarch64": {
        "msgget": 186, "semget": 190, "shmget": 194, "io_uring_setup": 425, "io_uring_enter": 426,
        "io_uring_register": 427, "unshare": 97, "setns": 268, "add_key": 217, "request_key": 218,
        "keyctl": 219, "bpf": 280, "perf_event_open": 241, "userfaultfd": 282, "clone": 220, "clone3": 435,
        "read": 63, "write": 64, "exit_group": 94,
    },
}
REFUSED_CALLS = (
    "shmget", "semget", "msgget", "io_uring_setup", "io_uring_enter", "io_uring_register", "unshare",
    "setns", "add_key", "request_key", "keyctl", "bpf", "perf_event_open", "userfaultfd",
)
CLONE_NEWNS, CLONE_NEWCGROUP, CLONE_NEWUTS, CLONE_NEWIPC = 0x00020000, 0x02000000, 0x04000000, 0x08000000
CLONE_NEWUSER, CLONE_NEWPID, CLONE_NEWNET = 0x10000000, 0x20000000, 0x40000000
NAMESPACE_FLAGS = (CLONE_NEWNS, CLONE_NEWCGROUP, CLONE_NEWUTS, CLONE_NEWIPC, CLONE_NEWUSER, CLONE_NEWPID, CLONE_NEWNET)
# What glibc's pthread_create passes to clone when clone3 answers ENOSYS.
THREAD_FLAGS = 0x003D0F00


def run_filter(program: bytes, arch: int, number: int, first_argument: int = 0) -> int:
    """What the classic BPF program returns for a system call, as the kernel would run it."""
    data = {0: number, 4: arch, 16: first_argument & 0xFFFFFFFF, 20: first_argument >> 32}
    statements = [program[index : index + 8] for index in range(0, len(program), 8)]
    accumulator = 0
    index = 0
    while True:
        code, jump_true, jump_false, value = struct.unpack("<HBBI", statements[index])
        if code == LOAD_WORD:
            accumulator = data[value]
        elif code == RETURN:
            return value
        else:
            taken = {
                JUMP_IF_EQUAL: accumulator == value,
                JUMP_IF_AT_LEAST: accumulator >= value,
                JUMP_IF_ANY_BIT: bool(accumulator & value),
            }[code]
            index += jump_true if taken else jump_false
        index += 1


@pytest.mark.parametrize("machine", sorted(ARCHITECTURES))
def test_the_filter_names_the_kernels_numbers(machine):
    calls = ARCHITECTURES[machine].system_calls
    expected = KERNEL_NUMBERS[machine]

    assert set(calls.refused) == set(REFUSED_CALLS)
    assert {name: number for name, number in calls.refused.items()} == {name: expected[name] for name in REFUSED_CALLS}
    assert (calls.clone, calls.clone3) == (expected["clone"], expected["clone3"])
    assert CLONE_NAMESPACE_FLAGS == sum(NAMESPACE_FLAGS)


@pytest.mark.parametrize("machine", sorted(ARCHITECTURES))
def test_the_filter_refuses_its_calls_and_namespaced_clones_and_allows_the_rest(machine):
    program = plugin_filter(machine)
    arch = ARCHITECTURES[machine].audit_arch
    numbers = KERNEL_NUMBERS[machine]

    for name in REFUSED_CALLS:
        assert run_filter(program, arch, numbers[name]) == REFUSED, name
    assert run_filter(program, arch, numbers["clone3"]) == NOT_IMPLEMENTED
    for flag in NAMESPACE_FLAGS:
        assert run_filter(program, arch, numbers["clone"], THREAD_FLAGS | flag) == REFUSED, hex(flag)
    # The high half of clone's flags is not read by the kernel, so it does not matter here either.
    assert run_filter(program, arch, numbers["clone"], THREAD_FLAGS | 1 << 40) == SECCOMP_RET_ALLOW
    assert run_filter(program, arch, numbers["clone"], THREAD_FLAGS) == SECCOMP_RET_ALLOW
    for name in ("read", "write", "exit_group", "vfork"):
        if name in numbers:
            assert run_filter(program, arch, numbers[name]) == SECCOMP_RET_ALLOW, name


@pytest.mark.parametrize("machine", sorted(ARCHITECTURES))
def test_another_abi_is_refused(machine):
    program = plugin_filter(machine)
    other = next(architecture for name, architecture in ARCHITECTURES.items() if name != machine)

    assert run_filter(program, other.audit_arch, KERNEL_NUMBERS[machine]["read"]) == REFUSED
    if ARCHITECTURES[machine].has_x32:
        assert run_filter(program, ARCHITECTURES[machine].audit_arch, 0x40000000 | 0) == REFUSED


def test_an_unknown_architecture_has_no_filter():
    with pytest.raises(ValueError, match="no plugin seccomp filter is known for riscv64"):
        plugin_filter("riscv64")


# Each refused call with arguments the kernel would turn down before doing anything: so without
# the filter the answer is a specific error (or 0 for unshare(0)), and with it EPERM. Prints the
# results as {call: return value or -errno}, then whether Python's threads, subprocesses, fork and
# asyncio still worked.
PROBE = r"""
import asyncio, ctypes, json, os, subprocess, sys, threading
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
numbers = json.loads(sys.argv[2])
if sys.argv[1] == "filtered":
    sys.path.insert(0, sys.argv[3])
    from es_plugins.launcher.plugin_seccomp import install_filter, plugin_filter
    assert libc.prctl(38, 1, 0, 0, 0) == 0  # PR_SET_NO_NEW_PRIVS
    install_filter(plugin_filter())

def raw(name, *arguments):
    ctypes.set_errno(0)
    value = libc.syscall(ctypes.c_long(numbers[name]), *[ctypes.c_long(argument) for argument in arguments])
    return -ctypes.get_errno() if value < 0 else value

def wrapped(function, *arguments):
    try:
        function(*arguments)
        return 0
    except OSError as error:
        return -error.errno

results = {
    "unshare(0)": wrapped(os.unshare, 0),
    "setns": wrapped(os.setns, 1 << 30, 0),
    "keyctl": raw("keyctl", 9999, 0, 0, 0, 0),
    "add_key": raw("add_key", 0, 0, 0, 0, 0),
    "request_key": raw("request_key", 0, 0, 0, 0),
    "perf_event_open": raw("perf_event_open", 0, 0, -1, -1, 0),
    "clone3": raw("clone3", 0, 0),
    "bpf": raw("bpf", 9999, 0, 0),
    "userfaultfd": raw("userfaultfd", 1 | 4),
    "io_uring_setup": raw("io_uring_setup", 1, 0),
}
# CLONE_THREAD without CLONE_SIGHAND: the kernel refuses it before it makes anything.
for name, flag in json.loads(sys.argv[4]).items():
    results[f"clone({name})"] = raw("clone", flag | 0x10000, 0, 0, 0, 0)
if sys.argv[1] == "filtered":
    # Without the filter it would put this process in a namespace of its own.
    results["unshare(CLONE_NEWUSER)"] = wrapped(os.unshare, os.CLONE_NEWUSER)

ran = []
thread = threading.Thread(target=lambda: ran.append("thread"))
thread.start()
thread.join()
ran.append(subprocess.run([sys.executable, "-c", "print('child')"], capture_output=True, text=True).stdout.strip())
child = os.fork()
if child == 0:
    os._exit(7)
ran.append(os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]))
async def asynchronous():
    process = await asyncio.create_subprocess_exec("true")
    return await process.wait()
ran.append(asyncio.run(asynchronous()))
print(json.dumps({"results": results, "python": ran}))
"""
NAMED_FLAGS = {
    "CLONE_NEWNS": CLONE_NEWNS, "CLONE_NEWCGROUP": CLONE_NEWCGROUP, "CLONE_NEWUTS": CLONE_NEWUTS,
    "CLONE_NEWIPC": CLONE_NEWIPC, "CLONE_NEWUSER": CLONE_NEWUSER, "CLONE_NEWPID": CLONE_NEWPID,
    "CLONE_NEWNET": CLONE_NEWNET,
}
# Without the filter: refused before doing anything, so these answers do not depend on the host.
UNFILTERED = {
    "unshare(0)": 0,
    "setns": -errno.EBADF,
    "keyctl": -errno.EOPNOTSUPP,
    "add_key": -errno.EFAULT,
    "request_key": -errno.EFAULT,
    "clone3": -errno.EINVAL,
    **{f"clone({name})": -errno.EINVAL for name in NAMED_FLAGS},
}
# Without the filter, these answer an error that depends on the host, but never EPERM: a kernel
# that restricts perf events (Ubuntu's kernel.perf_event_paranoid above 2) answers EACCES before
# it reads the attributes, and EFAULT otherwise.
NOT_EPERM_UNFILTERED = ("perf_event_open",)
# Without the filter, a host setting may refuse these with EPERM itself.
HOST_SETTINGS = {
    "bpf": "kernel.unprivileged_bpf_disabled",
    "userfaultfd": "vm.unprivileged_userfaultfd",
    "io_uring_setup": "kernel.io_uring_disabled",
}


def probe(mode: str) -> dict:
    numbers = KERNEL_NUMBERS[os.uname().machine]
    completed = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, mode, json.dumps(numbers), str(ES_PLUGINS), json.dumps(NAMED_FLAGS)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(completed.stdout)


def already_filtered() -> bool:
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    return status.get("Seccomp", "0").strip() != "0"


@pytest.mark.linux
def test_under_the_filter_each_call_is_refused_and_clone3_is_not_implemented():
    results = probe("filtered")["results"]

    assert results.pop("clone3") == -errno.ENOSYS
    assert results == dict.fromkeys(results, -errno.EPERM)
    assert len(results) == 10 + len(NAMED_FLAGS)


@pytest.mark.linux
def test_under_the_filter_pythons_threads_subprocesses_fork_and_asyncio_work():
    assert probe("filtered")["python"] == ["thread", "child", 7, 0]


@pytest.mark.linux
def test_without_the_filter_the_same_calls_get_other_answers():
    if already_filtered():
        pytest.skip("the tests run under a seccomp filter already (the container's profile), which refuses these itself")

    results = probe("unfiltered")["results"]

    assert {name: results[name] for name in UNFILTERED} == UNFILTERED
    assert {name: results[name] for name in NOT_EPERM_UNFILTERED if results[name] == -errno.EPERM} == {}


@pytest.mark.linux
@pytest.mark.parametrize("call", sorted(HOST_SETTINGS))
def test_without_the_filter_a_call_a_host_setting_may_refuse_is_not_refused_by_default(call):
    if already_filtered():
        pytest.skip("the tests run under a seccomp filter already (the container's profile), which refuses these itself")
    answer = probe("unfiltered")["results"][call]
    if answer == -errno.EPERM:
        pytest.skip(f"this host refuses {call} itself ({HOST_SETTINGS[call]}): the filtered result proves nothing for it here")

    assert answer != -errno.EPERM


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
# io_uring_setup(1, NULL): EPERM under the filter (EFAULT, or a ring, without it).
ring = libc.syscall(425, 1, None)
results.append(-ctypes.get_errno() if ring < 0 else ring)
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
                argv=[SYSTEM_PYTHON, "-I", "-c", SYSTEM_V_AND_OTHERS],
                environment={"PATH": "/usr/bin:/bin"},
                working_directory=Path("/"),
                output_descriptor=descriptor.fileno(),
                seccomp_filter=plugin_filter(),
            )
        )
    finally:
        descriptor.close()
    os.waitpid(pid, 0)
    assert json.loads(output.read_text()) == [-errno.EPERM, -errno.EPERM, -errno.EPERM, -errno.EPERM, True]


@pytest.mark.root
def test_without_the_filter_the_same_calls_work():
    completed = subprocess.run([sys.executable, "-I", "-c", SYSTEM_V_AND_OTHERS], capture_output=True, text=True, check=True)

    shm, msg, sem, ring, _ = json.loads(completed.stdout)
    assert shm >= 0 and msg >= 0 and sem >= 0
    if ring == -errno.EPERM:
        pytest.skip("io_uring is refused here without the filter too (the container's seccomp profile or kernel.io_uring_disabled)")
    assert ring != -errno.EPERM
