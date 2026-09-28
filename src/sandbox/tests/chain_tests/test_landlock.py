"""Coverage for landlock.apply(): ruleset construction with the kernel faked
out, and signal isolation enforced by the real kernel.

Fake-kernel tests: only the syscall boundary is replaced. `_libc` records what
apply() hands the kernel, and `abi_version` is pinned so every ABI branch runs
on any host.

Real-kernel tests (the `...OnKernel` / `...SurvivesLauncherExecv` classes) need
Landlock ABI 6+ (Linux 6.12+) and are skipped below it; the fake-kernel tests
still run there. Signal isolation is irreversible once applied, so, as in
test_seccomp.py, every isolated process here is a fresh subprocess -- never the
pytest process itself.

Safety: a signal isolation failure must not be able to hurt the test runner or
the developer's session. The targeted-kill tests only ever aim at a dedicated
sibling process by pid. The broadcast `kill(-1, SIGKILL)` test runs entirely
inside a new user + PID namespace: there `kill(-1)` can only reach processes
in that namespace, so even an unisolated broadcast kills nothing outside it.
The test is skipped where such a namespace cannot be created.

Note on `kill(-1)`: Linux ignores per-target EPERM for the broadcast case, so
under signal isolation `kill(-1, sig)` returns success while delivering
nothing. The broadcast test therefore asserts that the sibling survives, not
that the call raises.
"""

import ctypes
import json
import os
import select
import signal
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: Landlock is Linux-specific; runs in the Linux image",
)

import landlock
from dynamic_venv_executor_chain import LAUNCHER_PATH
from jail import build_jail

_SIGNAL_ISOLATION_BITS = (
    landlock._LANDLOCK_SCOPE_SIGNAL | landlock._LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET
)
_NET_BITS = landlock._LANDLOCK_ACCESS_NET_BIND_TCP | landlock._LANDLOCK_ACCESS_NET_CONNECT_TCP

# Applied per class, not per module, so the fake-kernel tests still run on
# ABI 1-5 hosts.
_requires_signal_isolation_kernel = pytest.mark.skipif(
    landlock.abi_version() < landlock.MIN_ABI_FOR_SIGNAL_ISOLATION,
    reason="needs Landlock ABI 6+ (Linux 6.12+)",
)


# Relies on ctypes byref() internals (`_obj`) to read the structs apply() passes to the syscall.
class _FakeLibc:
    """Stands in for the kernel: records each Landlock syscall apply() makes."""

    def __init__(self) -> None:
        self.ruleset_attr: dict[str, int] | None = None
        self.ruleset_attr_size: int | None = None
        self.net_rule_ports: list[int] = []
        self.restricted = False

    def syscall(self, number, *args):
        if number.value == landlock._SYS_LANDLOCK_CREATE_RULESET:
            attr = args[0]._obj
            self.ruleset_attr = {
                "handled_access_fs": attr.handled_access_fs,
                "handled_access_net": attr.handled_access_net,
                "scoped": attr.scoped,
            }
            self.ruleset_attr_size = args[1].value
            # A real fd, so apply()'s os.close() in `finally` closes something it owns.
            return os.open(os.devnull, os.O_RDONLY)
        if number.value == landlock._SYS_LANDLOCK_ADD_RULE:
            if args[1].value == landlock._LANDLOCK_RULE_NET_PORT:
                self.net_rule_ports.append(args[2]._obj.port)
            return 0
        if number.value == landlock._SYS_LANDLOCK_RESTRICT_SELF:
            self.restricted = True
            return 0
        raise AssertionError(f"unexpected syscall {number.value}")

    def prctl(self, *args):
        return 0


@pytest.fixture
def fake_libc(monkeypatch):
    fake = _FakeLibc()
    monkeypatch.setattr(landlock, "_libc", fake)
    return fake


def _pin_abi(monkeypatch, abi: int) -> None:
    monkeypatch.setattr(landlock, "abi_version", lambda: abi)


def _apply(**kwargs) -> None:
    landlock.apply(rw_paths=[], ro_paths=[], roexec_paths=[], **kwargs)


class TestRulesetAttrLayout:
    def test_struct_layout_matches_the_explicit_sizes(self):
        assert ctypes.sizeof(landlock._RulesetAttr) == landlock._RULESET_ATTR_SIZE_FS_NET_AND_SCOPE
        assert landlock._RulesetAttr.handled_access_net.offset == (
            landlock._RULESET_ATTR_SIZE_FS_ONLY
        )
        assert landlock._RulesetAttr.scoped.offset == landlock._RULESET_ATTR_SIZE_FS_AND_NET


class TestApplyRulesetSize:
    def test_filesystem_only_passes_size_8(self, fake_libc, monkeypatch):
        _pin_abi(monkeypatch, 8)

        _apply()

        assert fake_libc.ruleset_attr_size == 8
        assert fake_libc.ruleset_attr["handled_access_net"] == 0
        assert fake_libc.ruleset_attr["scoped"] == 0
        assert fake_libc.restricted

    def test_network_without_signal_isolation_passes_size_16(self, fake_libc, monkeypatch):
        _pin_abi(monkeypatch, 4)

        _apply(allowed_tcp_ports=(9000,))

        assert fake_libc.ruleset_attr_size == 16
        assert fake_libc.ruleset_attr["handled_access_net"] == _NET_BITS
        assert fake_libc.ruleset_attr["scoped"] == 0
        assert fake_libc.net_rule_ports == [9000]

    def test_signal_isolation_only_passes_size_24_with_net_unhandled(
        self, fake_libc, monkeypatch
    ):
        _pin_abi(monkeypatch, 6)

        _apply(isolate_signals=True)

        assert fake_libc.ruleset_attr_size == 24
        assert fake_libc.ruleset_attr["scoped"] == _SIGNAL_ISOLATION_BITS
        assert fake_libc.ruleset_attr["handled_access_net"] == 0
        assert fake_libc.net_rule_ports == []
        assert fake_libc.restricted

    def test_signal_isolation_with_network_passes_size_24_with_both(
        self, fake_libc, monkeypatch
    ):
        _pin_abi(monkeypatch, 6)

        _apply(allowed_tcp_ports=(9000,), isolate_signals=True)

        assert fake_libc.ruleset_attr_size == 24
        assert fake_libc.ruleset_attr["scoped"] == _SIGNAL_ISOLATION_BITS
        assert fake_libc.ruleset_attr["handled_access_net"] == _NET_BITS
        assert fake_libc.net_rule_ports == [9000]

    def test_isolation_bits_match_the_kernel_uapi(self):
        """Pin the include/uapi/linux/landlock.h values, for CI hosts without ABI 6."""
        assert landlock._LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET == 1 << 0
        assert landlock._LANDLOCK_SCOPE_SIGNAL == 1 << 1


class TestApplySignalIsolationUnavailable:
    @pytest.mark.parametrize("abi", [1, 4, 5])
    def test_signal_isolation_on_old_abi_raises_before_creating_a_ruleset(
        self, fake_libc, monkeypatch, abi
    ):
        _pin_abi(monkeypatch, abi)

        with pytest.raises(landlock.LandlockSignalIsolationUnavailableError):
            _apply(isolate_signals=True)

        assert fake_libc.ruleset_attr is None
        assert not fake_libc.restricted

    def test_no_landlock_still_raises_the_filesystem_error_first(self, fake_libc, monkeypatch):
        _pin_abi(monkeypatch, 0)

        with pytest.raises(landlock.LandlockUnavailableError):
            _apply(isolate_signals=True)


_SANDBOX_DIR = LAUNCHER_PATH.parent

# Imports happen before apply(): the empty allowlist denies all filesystem
# access afterwards, so nothing can be imported once the ruleset is in force.
_PRELUDE = "import os, signal, socket, sys, time\nimport landlock\n"
_APPLY_SIGNAL_ISOLATION = "landlock.apply([], [], [], isolate_signals=True)\n"

_NAMESPACE_UNAVAILABLE_EXIT_CODE = 77
_SIBLING_KILLED_EXIT_CODE = 3
_ATTACKER_FAILED_EXIT_CODE = 4
_SLEEPER_READY_TIMEOUT_SECONDS = 10
# How long the broadcast test watches the sibling after the attack. A
# SIGKILL'd sibling is reaped within milliseconds, so surviving this long
# means the signal was not delivered.
_SIBLING_SURVIVAL_WINDOW_SECONDS = 1


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(_SANDBOX_DIR)}


def _run(snippet: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", snippet, *args],
        capture_output=True,
        text=True,
        env=_env(),
        timeout=30,
    )


def _start_sleeper(*, isolated: bool) -> subprocess.Popen:
    """Start a process that sleeps until killed, once it is fully set up."""
    snippet = (
        _PRELUDE
        + (_APPLY_SIGNAL_ISOLATION if isolated else "")
        + "print('ready', flush=True)\n"
        + "while True:\n    time.sleep(1)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", snippet],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(),
    )
    # Bounded, so a child that stalls before "ready" fails the test instead
    # of hanging the whole suite on readline().
    readable, _, _ = select.select([process.stdout], [], [], _SLEEPER_READY_TIMEOUT_SECONDS)
    if not readable:
        process.kill()
        process.wait(timeout=5)
        pytest.fail(f"sleeper did not report ready within {_SLEEPER_READY_TIMEOUT_SECONDS}s")
    ready_line = process.stdout.readline().strip()
    if ready_line != "ready":
        process.kill()
        process.wait(timeout=5)
        pytest.fail(f"sleeper failed to start: {process.stderr.read()}")
    return process


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _assert_still_running(process: subprocess.Popen) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        process.wait(timeout=0.5)


@pytest.fixture
def unisolated_sibling():
    sibling = _start_sleeper(isolated=False)
    yield sibling
    _stop(sibling)


@pytest.fixture
def isolated_sibling():
    sibling = _start_sleeper(isolated=True)
    yield sibling
    _stop(sibling)


_KILL_SIBLING = (
    "try:\n"
    "    os.kill(int(sys.argv[1]), signal.SIGKILL)\n"
    "except PermissionError:\n"
    "    sys.exit(0)\n"
    "sys.exit('kill of the sibling was allowed')\n"
)


@_requires_signal_isolation_kernel
class TestSignalIsolationOnKernel:
    def test_isolated_process_cannot_kill_an_unisolated_sibling(self, unisolated_sibling):
        result = _run(
            _PRELUDE + _APPLY_SIGNAL_ISOLATION + _KILL_SIBLING, str(unisolated_sibling.pid)
        )

        assert result.returncode == 0, result.stderr
        _assert_still_running(unisolated_sibling)

    def test_isolated_process_cannot_kill_a_sibling_in_its_own_separate_domain(
        self, isolated_sibling
    ):
        """The production case: two executions, each with its own domain."""
        result = _run(
            _PRELUDE + _APPLY_SIGNAL_ISOLATION + _KILL_SIBLING, str(isolated_sibling.pid)
        )

        assert result.returncode == 0, result.stderr
        _assert_still_running(isolated_sibling)

    def test_unisolated_process_can_kill_a_sibling(self, unisolated_sibling):
        """Proves the harness is not what protects the sibling above: same
        uid, no signal isolation, and the kill goes through."""
        result = _run(
            _PRELUDE + "os.kill(int(sys.argv[1]), signal.SIGKILL)\n", str(unisolated_sibling.pid)
        )

        assert result.returncode == 0, result.stderr
        assert unisolated_sibling.wait(timeout=5) == -signal.SIGKILL

    def test_isolated_process_can_still_kill_its_own_child(self):
        snippet = (
            _PRELUDE
            + _APPLY_SIGNAL_ISOLATION
            + "child = os.fork()\n"
            + "if child == 0:\n"
            + "    while True:\n"
            + "        time.sleep(1)\n"
            + "os.kill(child, signal.SIGKILL)\n"
            + "_, status = os.waitpid(child, 0)\n"
            + "assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL, status\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr

    def test_parent_can_still_kill_an_isolated_child(self):
        """The supervisor's timeout kill must keep working."""
        child = _start_sleeper(isolated=True)
        try:
            child.kill()
            assert child.wait(timeout=5) == -signal.SIGKILL
        finally:
            _stop(child)

    @pytest.mark.parametrize(
        ("mode", "expected_exit_code"),
        [("isolated", 0), ("unisolated", _SIBLING_KILLED_EXIT_CODE)],
    )
    def test_broadcast_kill_reaches_a_sibling_only_without_signal_isolation(
        self, mode, expected_exit_code
    ):
        """Runs inside a new user + PID namespace (see module docstring).

        PID 1 of the namespace forks a sleeping sibling and an attacker that
        calls kill(-1, SIGKILL). kill(-1) never targets PID 1, so PID 1
        survives either way and reports whether the sibling did. The
        unisolated run is the control: it shows the broadcast really does kill
        the sibling when nothing stops it.

        The attacker must exit 0 before the sibling is judged: if apply()
        or the kill itself failed, the sibling would survive for the wrong
        reason and the isolated case would pass without proving anything.
        """
        snippet = (
            _PRELUDE
            + "try:\n"
            + "    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWPID)\n"
            + "except OSError:\n"
            + f"    sys.exit({_NAMESPACE_UNAVAILABLE_EXIT_CODE})\n"
            + "namespace_init = os.fork()\n"
            + "if namespace_init == 0:\n"
            + "    sibling = os.fork()\n"
            + "    if sibling == 0:\n"
            + "        while True:\n"
            + "            time.sleep(1)\n"
            + "    attacker = os.fork()\n"
            + "    if attacker == 0:\n"
            + "        try:\n"
            + "            if sys.argv[1] == 'isolated':\n"
            + "                landlock.apply([], [], [], isolate_signals=True)\n"
            + "            os.kill(-1, signal.SIGKILL)\n"
            + "        except BaseException as error:\n"
            + "            print(f'attacker failed: {error!r}', file=sys.stderr, flush=True)\n"
            + f"            os._exit({_ATTACKER_FAILED_EXIT_CODE})\n"
            + "        os._exit(0)\n"
            + "    _, attacker_status = os.waitpid(attacker, 0)\n"
            + "    if os.waitstatus_to_exitcode(attacker_status) != 0:\n"
            + "        os.kill(sibling, signal.SIGKILL)\n"
            + "        os.waitpid(sibling, 0)\n"
            + f"        os._exit({_ATTACKER_FAILED_EXIT_CODE})\n"
            + f"    deadline = time.monotonic() + {_SIBLING_SURVIVAL_WINDOW_SECONDS}\n"
            + "    while time.monotonic() < deadline:\n"
            + "        reaped_pid, _ = os.waitpid(sibling, os.WNOHANG)\n"
            + "        if reaped_pid != 0:\n"
            + f"            os._exit({_SIBLING_KILLED_EXIT_CODE})\n"
            + "        time.sleep(0.05)\n"
            + "    os.kill(sibling, signal.SIGKILL)\n"
            + "    os.waitpid(sibling, 0)\n"
            + "    os._exit(0)\n"
            + "_, status = os.waitpid(namespace_init, 0)\n"
            + "sys.exit(os.waitstatus_to_exitcode(status))\n"
        )

        result = _run(snippet, mode)

        if result.returncode == _NAMESPACE_UNAVAILABLE_EXIT_CODE:
            pytest.skip("unprivileged user + PID namespaces are unavailable here")
        assert result.returncode == expected_exit_code, result.stderr


@_requires_signal_isolation_kernel
class TestAbstractUnixSocketIsolationOnKernel:
    @pytest.fixture
    def outside_listener(self):
        """Yield the socket's abstract name, without the leading NUL byte."""
        name = f"epicstaff-landlock-isolation-test-{uuid.uuid4().hex}"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(f"\0{name}")
        listener.listen(1)
        yield name
        listener.close()

    def test_isolated_process_cannot_connect_to_an_outside_abstract_socket(
        self, outside_listener
    ):
        snippet = (
            _PRELUDE
            + "client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            + _APPLY_SIGNAL_ISOLATION
            + "try:\n"
            + "    client.connect('\\0' + sys.argv[1])\n"
            + "except PermissionError:\n"
            + "    sys.exit(0)\n"
            + "sys.exit('connect to the outside abstract socket was allowed')\n"
        )

        result = _run(snippet, outside_listener)

        assert result.returncode == 0, result.stderr

    def test_unisolated_process_can_connect_to_an_outside_abstract_socket(
        self, outside_listener
    ):
        """Control: the socket is reachable when nothing isolates the client."""
        snippet = (
            _PRELUDE
            + "client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            + "client.connect('\\0' + sys.argv[1])\n"
        )

        result = _run(snippet, outside_listener)

        assert result.returncode == 0, result.stderr

    def test_isolated_process_can_use_an_abstract_socket_inside_its_own_domain(self):
        snippet = (
            _PRELUDE
            + _APPLY_SIGNAL_ISOLATION
            + "address = '\\0epicstaff-landlock-isolation-self-' + str(os.getpid())\n"
            + "listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            + "listener.bind(address)\n"
            + "listener.listen(1)\n"
            + "client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            + "client.connect(address)\n"
        )

        result = _run(snippet)

        assert result.returncode == 0, result.stderr


@_requires_signal_isolation_kernel
class TestSignalIsolationSurvivesLauncherExecv:
    def test_signal_isolation_from_the_plan_survives_execv_into_job_code(
        self, tmp_path, unisolated_sibling
    ):
        """End to end: launcher.py applies the plan, execs the job, and the job
        code -- not just the launcher -- is still unable to kill the sibling."""
        jail = build_jail(
            exec_dir=tmp_path,
            venv_path=Path(sys.prefix),
            savefiles_root=tmp_path,
        )
        # The venv's interpreter may live outside it (a symlink into a
        # pyenv/uv install on a dev host), so its real install must be
        # executable too for the job to start.
        plan = {
            "jail": {**asdict(jail), "read_exec": [*jail.read_exec, sys.base_prefix]},
            "network": {"mode": "unrestricted"},
            "isolate_signals": True,
        }
        job_path = tmp_path / "job.py"
        job_path.write_text(
            "import os, signal, sys\n"
            "try:\n"
            f"    os.kill({unisolated_sibling.pid}, signal.SIGKILL)\n"
            "except PermissionError:\n"
            "    sys.exit(0)\n"
            "sys.exit('job code killed the sibling')\n"
        )

        result = subprocess.run(
            [sys.executable, str(LAUNCHER_PATH), json.dumps(plan), sys.executable, str(job_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        _assert_still_running(unisolated_sibling)
