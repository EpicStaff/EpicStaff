"""Concurrency tests for venv creation and library installation.

Validates that asyncio locks prevent race conditions when multiple concurrent
runs try to create or install libraries in the same venv path.
"""

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import DynamicVenvExecutorChain


class _FakeProcess:
    """Minimal asyncio.subprocess.Process look-alike."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode

    async def communicate(self):
        return (b"", b"")


class _FakeShell:
    """Fake for asyncio.create_subprocess_shell, used for `python -m venv <path>`.

    Creates the venv directory on disk and records each call's command, venv
    path, and start/end timestamps (needed to check whether two calls
    overlapped). Set `.delay` before use to simulate slow venv creation.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.delay: float = 0.0

    async def __call__(self, cmd: str, **kwargs):
        start = asyncio.get_event_loop().time()
        venv_path_str = cmd.strip().split()[-1]
        if self.delay:
            await asyncio.sleep(self.delay)
        Path(venv_path_str).mkdir(parents=True, exist_ok=True)
        end = asyncio.get_event_loop().time()
        self.calls.append({"cmd": cmd, "venv_path": venv_path_str, "start": start, "end": end})
        return _FakeProcess()


class _FakeExec:
    """Fake for asyncio.create_subprocess_exec, used for pip and code-execution calls.

    Records every call with its args and start/end timestamps. Recognizes two
    call shapes:
    - `pip install -- <library>`: counted in `pip_install_counts[library]`;
      fails with returncode=1 while `fail_installs_remaining` is positive
    - code execution (last arg ends with "code.py"): writes `expected_result`
      to the matching output.txt, after waiting `exec_delay` seconds
    """

    def __init__(self, expected_result: object = 1):
        self.calls: list[dict] = []
        self.pip_install_counts: dict[str, int] = {}
        self.exec_delay: float = 0.0
        self.fail_installs_remaining: int = 0
        self.expected_result = expected_result

    async def __call__(self, *args, **kwargs):
        start = asyncio.get_event_loop().time()
        is_install = (
            len(args) >= 5 and args[2] == "pip" and args[3] == "install" and args[4] != "--upgrade"
        )
        returncode = 0

        if is_install:
            library = str(args[-1])
            self.pip_install_counts[library] = self.pip_install_counts.get(library, 0) + 1
            if self.fail_installs_remaining > 0:
                self.fail_installs_remaining -= 1
                returncode = 1
        else:
            last_arg = str(args[-1]) if args else ""
            if last_arg.endswith("code.py"):
                if self.exec_delay:
                    await asyncio.sleep(self.exec_delay)
                Path(last_arg.replace("code.py", "output.txt")).write_text(
                    json.dumps(self.expected_result), encoding="utf-8"
                )

        end = asyncio.get_event_loop().time()
        self.calls.append({"args": args, "start": start, "end": end})
        return _FakeProcess(returncode=returncode)


@pytest.fixture
def _fake_shell(monkeypatch):
    """Patch asyncio.create_subprocess_shell with a fake venv-creation call."""
    fake = _FakeShell()
    monkeypatch.setattr(dynamic_venv_executor_chain.asyncio, "create_subprocess_shell", fake)
    return fake


@pytest.fixture
def _fake_exec(monkeypatch):
    """Patch asyncio.create_subprocess_exec with a fake pip/code-execution call."""
    fake = _FakeExec()
    monkeypatch.setattr(dynamic_venv_executor_chain.asyncio, "create_subprocess_exec", fake)
    return fake


def _run_simple_flow(chain: DynamicVenvExecutorChain, libraries: list[str], execution_id: str):
    return chain.run(
        libraries=libraries,
        venv_name="test-venv",
        execution_id=execution_id,
        code="def main(**kwargs):\n    return 1",
        entrypoint="main",
    )


@pytest.mark.asyncio
async def test_second_concurrent_run_waits_for_venv_creation_to_complete(tmp_path, _fake_shell, _fake_exec):
    """Two concurrent runs trying to create the same venv serialize venv creation."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    _fake_shell.delay = 0.01

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)

    result_a, result_b = await asyncio.gather(
        _run_simple_flow(chain, ["requests"], "task-a"),
        _run_simple_flow(chain, ["requests"], "task-b"),
    )

    assert result_a.returncode == 0, f"Task A failed: {result_a.stderr}"
    assert result_b.returncode == 0, f"Task B failed: {result_b.stderr}"
    assert len(_fake_shell.calls) == 1, f"Expected 1 shell call (venv creation), got {len(_fake_shell.calls)}"


@pytest.mark.asyncio
async def test_install_executed_once_for_concurrent_identical_libraries(tmp_path, _fake_shell, _fake_exec):
    """Two concurrent runs with identical libraries execute install once each."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)
    libraries = ["requests==2.28.0", "numpy==1.24.0"]

    result_a, result_b = await asyncio.gather(
        _run_simple_flow(chain, libraries, "task-a"),
        _run_simple_flow(chain, libraries, "task-b"),
    )

    assert result_a.returncode == 0
    assert result_b.returncode == 0
    assert len(_fake_shell.calls) == 1

    # Task A installs, task B's install is skipped because the hash file already matches.
    for library in libraries:
        call_count = _fake_exec.pip_install_counts.get(library, 0)
        assert call_count == 1, f"Expected pip install for {library} to be called once, got {call_count}"


@pytest.mark.asyncio
async def test_different_library_sets_do_not_serialize(tmp_path, _fake_shell, _fake_exec):
    """Concurrent runs with different libraries use different venvs and don't serialize."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    _fake_shell.delay = 0.02

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)

    result_a, result_b = await asyncio.gather(
        _run_simple_flow(chain, ["requests==2.28.0"], "task-a"),
        _run_simple_flow(chain, ["numpy==1.24.0"], "task-b"),
    )

    assert result_a.returncode == 0
    assert result_b.returncode == 0

    shell_calls = _fake_shell.calls
    assert len(shell_calls) == 2, f"Expected 2 shell calls (different venvs), got {len(shell_calls)}"

    # Tasks overlap if one starts before the other finishes.
    call_a, call_b = shell_calls
    assert call_a["start"] < call_b["end"] and call_b["start"] < call_a["end"], (
        "Expected venv creation for different library sets to run concurrently"
    )


@pytest.mark.asyncio
async def test_code_execution_is_not_serialized(tmp_path, _fake_shell, _fake_exec):
    """Code execution for the same venv is NOT serialized (runs concurrently)."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    _fake_exec.exec_delay = 0.01

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)

    result_a, result_b = await asyncio.gather(
        _run_simple_flow(chain, ["requests"], "task-a"),
        _run_simple_flow(chain, ["requests"], "task-b"),
    )

    assert result_a.returncode == 0
    assert result_b.returncode == 0

    code_calls = [call for call in _fake_exec.calls if str(call["args"][-1]).endswith("code.py")]
    window_a = next(call for call in code_calls if "task-a" in str(call["args"][-1]))
    window_b = next(call for call in code_calls if "task-b" in str(call["args"][-1]))

    overlap = window_a["start"] < window_b["end"] and window_b["start"] < window_a["end"]
    assert overlap, "Code execution should have been concurrent (overlapping), but was serialized"


@pytest.mark.asyncio
async def test_sequential_run_with_unchanged_hash_skips_install(tmp_path, _fake_shell, _fake_exec):
    """A second sequential run with unchanged libraries skips installation."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)
    libraries = ["requests==2.28.0"]

    result_1 = await _run_simple_flow(chain, libraries, "task-1")
    assert result_1.returncode == 0
    installs_after_first = sum(_fake_exec.pip_install_counts.values())

    result_2 = await _run_simple_flow(chain, libraries, "task-2")
    assert result_2.returncode == 0
    installs_after_second = sum(_fake_exec.pip_install_counts.values())

    assert installs_after_second == installs_after_first, (
        f"Expected no pip install calls on second run, but count went from "
        f"{installs_after_first} to {installs_after_second}"
    )


@pytest.mark.asyncio
async def test_failed_library_installation_still_releases_lock(tmp_path, _fake_shell, _fake_exec):
    """If library installation fails, the lock is still released for retry."""
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    _fake_exec.fail_installs_remaining = 1  # fails the first pip install call only

    chain = DynamicVenvExecutorChain(output_path=output_path, base_venv_path=base_venv_path)

    task_1 = asyncio.create_task(_run_simple_flow(chain, ["requests"], "task-1"))
    await asyncio.sleep(0.01)  # let task 1 take the lock before task 2 starts
    task_2 = asyncio.create_task(_run_simple_flow(chain, ["requests"], "task-2"))

    try:
        result_1, result_2 = await asyncio.wait_for(asyncio.gather(task_1, task_2), timeout=5.0)
    except asyncio.TimeoutError:
        pytest.fail("Tasks hung: lock was not released after first task's pip failure")

    assert result_1.returncode != 0, (
        f"Expected first task to fail on pip install, but got returncode {result_1.returncode}"
    )
    assert result_2 is not None, "Second task should have completed (not hung waiting for lock)"
