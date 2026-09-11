"""Execution TTL for ExecuteCodeHandler.

An infinite loop in user code must not hang the sandbox (and, through the
crew-side polling loop, the whole flow) forever. ExecuteCodeHandler.handle()
bounds `process.communicate()` with settings.EXECUTION_TIMEOUT and, on
timeout, kills the whole process group (the job was started with
start_new_session=True) so grandchildren the job spawned die with it.

These tests drive the real handler and a real subprocess -- the same approach
as test_execute_code_handler_env.py -- rather than mocking asyncio subprocess
calls, because the behavior under test (a hung process actually getting
killed, a real timeout firing) only shows up with a real process tree.
"""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import settings
import dynamic_venv_executor_chain as chain_mod
from dynamic_venv_executor_chain import ExecuteCodeHandler

# In the container epicstaff_secrets/dotdict are installed into the venv;
# running the generated source directly here needs them on PYTHONPATH instead.
SHARED_PATH = Path(__file__).resolve().parents[3] / "shared"


def _context(tmp_path: Path, **overrides) -> dict[str, Any]:
    exec_dir = tmp_path / "exec"
    home_path = exec_dir / "home"
    tmp_dir = exec_dir / "tmp"
    for directory in (exec_dir, home_path, tmp_dir):
        directory.mkdir(parents=True, exist_ok=True)

    context: dict[str, Any] = {
        "python_executable": sys.executable,
        "temp_code_path": exec_dir / "code.py",
        "result_file_path": exec_dir / "output.txt",
        "home_path": str(home_path),
        "tmp_path": str(tmp_dir),
        "work_dir": str(exec_dir),
        "code": "def main(**kwargs):\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "exec-timeout-test",
        "use_storage": False,
        "storage_allowed_paths": None,
        "storage_org_prefix": None,
        "secrets": {},
    }
    context.update(overrides)
    return context


@pytest.fixture(autouse=True)
def shared_libs_on_path(monkeypatch):
    """wrap_code's preamble always imports dotdict and epicstaff_secrets, so
    every execution needs them importable, whether or not the job code
    itself uses them."""
    real_build_base_env = chain_mod.build_base_env
    monkeypatch.setattr(
        chain_mod,
        "build_base_env",
        lambda pe: {**real_build_base_env(pe), "PYTHONPATH": str(SHARED_PATH)},
    )


def _run(context: dict[str, Any]):
    return asyncio.run(ExecuteCodeHandler().handle(context))


def _run_bounded(context: dict[str, Any], bound_seconds: float):
    """Run the handler under an explicit outer bound.

    Regression guard for the exact bug this suite covers: if _handle_timeout
    ever regains an unbounded await, the handler hangs forever and the test
    must fail loudly with a TimeoutError instead of hanging the whole suite.
    pytest-timeout is not a dependency of this service, so the bound is
    applied here rather than via a marker.
    """

    async def _runner():
        return await asyncio.wait_for(
            ExecuteCodeHandler().handle(context), timeout=bound_seconds
        )

    return asyncio.run(_runner())


def _wait_until_dead(pid: int, timeout: float = 5.0) -> bool:
    """Poll for a process's death rather than checking once.

    A process killed with SIGKILL can linger briefly as a zombie until its
    (possibly reparented) parent reaps it, so a single os.kill(pid, 0) check
    right after the handler returns would be flaky.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True
        time.sleep(0.1)
    return False


class TestExecutionTimeout:
    def test_infinite_loop_is_killed_and_reported_as_timeout(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)
        context = _context(
            tmp_path,
            code="def main(**kwargs):\n    while True:\n        pass",
        )

        result = _run(context)

        assert result.returncode == 124
        assert result.execution_id == context["execution_id"]
        assert "exceeded" in result.stderr.lower()
        assert "terminated" in result.stderr.lower()

    def test_fast_job_still_returns_zero(self, tmp_path, monkeypatch):
        """The timeout path must not regress the happy path."""
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 5)
        context = _context(tmp_path, code="def main(**kwargs):\n    return 1")

        result = _run(context)

        assert result.returncode == 0
        assert result.result_data == "1"

    @pytest.mark.skipif(
        os.name != "posix", reason="process-group kill (killpg) is POSIX-only"
    )
    def test_grandchild_process_dies_with_its_parent(self, tmp_path, monkeypatch):
        """start_new_session + killpg must reach children the job itself spawned,
        not just the job's own top-level process."""
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 3)
        context = _context(tmp_path)
        pid_file = Path(context["work_dir"]) / "grandchild.pid"

        job_code_lines = [
            "def main(**kwargs):",
            "    import subprocess",
            "    import sys",
            "    child = subprocess.Popen(",
            "        [sys.executable, '-c', 'import time; time.sleep(120)']",
            "    )",
            f"    with open(r'{pid_file.as_posix()}', 'w') as pid_handle:",
            "        pid_handle.write(str(child.pid))",
            "    while True:",
            "        pass",
        ]
        context["code"] = "\n".join(job_code_lines)

        result = _run(context)

        assert result.returncode == 124
        grandchild_pid = int(pid_file.read_text())
        assert _wait_until_dead(
            grandchild_pid
        ), f"grandchild pid {grandchild_pid} still alive after its parent was killed"

    def test_infinite_loop_with_undrained_stdout_does_not_hang(
        self, tmp_path, monkeypatch
    ):
        """Regression test for the hang this module fixes.

        A job that floods stdout while looping never lets the pipe drain on
        its own. The old _handle_timeout awaited process.wait() after
        cancelling communicate() via wait_for; with the readers cancelled and
        the pipe never disconnecting, that await never returned. The test
        itself is bounded so a real regression fails loudly instead of
        hanging the suite.
        """
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)
        context = _context(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import sys\n"
                "    while True:\n"
                "        sys.stdout.write('x' * 4096)\n"
                "        sys.stdout.flush()\n"
            ),
        )

        result = _run_bounded(context, bound_seconds=10)

        assert result.returncode == 124
        assert "exceeded" in result.stderr.lower()
        assert "terminated" in result.stderr.lower()

    def test_kill_permission_denied_still_reports_timeout(self, tmp_path, monkeypatch):
        """Regression test for the container missing CAP_KILL.

        When the sandbox drops the user-code child to a different UID
        (sandboxuser) but the container lacks CAP_KILL, both os.killpg and
        process.kill() raise PermissionError. _handle_timeout must still
        return a CodeResultData(returncode=124) instead of letting that
        PermissionError propagate out of the handler and hang the crew-side
        waiter forever -- the exact failure mode the drain fix was meant to
        end.
        """
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)
        context = _context(
            tmp_path,
            code="def main(**kwargs):\n    while True:\n        pass",
        )

        def _deny_killpg(pgid, sig):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(os, "killpg", _deny_killpg)

        original_create_subprocess_exec = asyncio.create_subprocess_exec
        spawned_pids: list[int] = []

        async def _tracking_create_subprocess_exec(*args, **kwargs):
            process = await original_create_subprocess_exec(*args, **kwargs)
            spawned_pids.append(process.pid)

            def _deny_kill():
                raise PermissionError(1, "Operation not permitted")

            monkeypatch.setattr(process, "kill", _deny_kill)
            return process

        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", _tracking_create_subprocess_exec
        )

        try:
            result = _run_bounded(context, bound_seconds=10)

            assert result.returncode == 124
            assert result.execution_id == context["execution_id"]
            assert "could not be terminated" in result.stderr.lower()
        finally:
            for pid in spawned_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    def test_partial_stdout_is_recovered_on_timeout(self, tmp_path, monkeypatch):
        """Proves the drain path works, rather than only returning empty output."""
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)
        marker = "PARTIAL_OUTPUT_MARKER"
        context = _context(
            tmp_path,
            code=(
                "def main(**kwargs):\n"
                "    import sys\n"
                f"    print('{marker}')\n"
                "    sys.stdout.flush()\n"
                "    while True:\n"
                "        pass\n"
            ),
        )

        result = _run_bounded(context, bound_seconds=10)

        assert result.returncode == 124
        assert marker in result.stdout
        assert "exceeded" in result.stderr.lower()
        assert "terminated" in result.stderr.lower()
