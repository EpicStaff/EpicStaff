"""The execution timeout the sandbox applies to a task, and how a run killed by it is reported.

Invariant: a task's requested timeout (`CodeTaskData.timeout`, seconds) applies as asked,
capped at SANDBOX_EXECUTION_TIMEOUT because the request is untrusted; a task without one
gets SANDBOX_DEFAULT_EXECUTION_TIMEOUT, also capped, or the maximum when there is no default
(never unbounded while a maximum is set). SANDBOX_EXECUTION_TIMEOUT=none means no cap. A run
killed for running past the applied timeout says so in its stderr, naming the limit that was
applied rather than the one requested.

The handler tests spawn a real hanging process, but without launcher.py: Landlock is
reported absent (`abi_version` -> 0) with isolation not required, so the child runs
unconfined. That keeps them independent of the uid the launcher needs, while the timeout,
the kill and the result are the real code paths.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain as chain_mod
import settings
from dynamic_venv_executor_chain import (
    AbstractHandler,
    DynamicVenvExecutorChain,
    ExecuteCodeHandler,
    effective_execution_timeout,
)

from conftest import copy_shared_libs_into_jail, make_execute_context

HANGING_CODE = "def main(**kwargs):\n    import time\n    while True:\n        time.sleep(0.05)\n"
FINISHING_CODE = "def main(**kwargs):\n    return 'done'\n"
# Long enough that only the timeout under test can end a hanging run inside the bound.
LONG_SECONDS = 120
# Bounds every handler run so a timeout that is not applied fails the test instead of
# hanging the suite.
RUN_BOUND_SECONDS = 15


@pytest.mark.parametrize(
    ("requested_seconds", "max_seconds", "default_seconds", "expected"),
    [
        (30, 300, 60, 30),
        (300, 300, 60, 300),
        (600, 300, 60, 300),
        (None, 300, 60, 60),
        (None, 30, 60, 30),
        (None, 300, None, 300),
        (600, None, 60, 600),
        (None, None, 60, 60),
        (None, None, None, None),
    ],
    ids=[
        "requested-below-maximum",
        "requested-equal-to-maximum",
        "requested-above-maximum-is-capped",
        "not-requested-takes-default",
        "default-above-maximum-is-capped",
        "no-default-takes-maximum",
        "no-maximum-keeps-request",
        "no-maximum-not-requested-takes-default",
        "no-maximum-no-default-is-unbounded",
    ],
)
def test_effective_execution_timeout(
    monkeypatch, requested_seconds, max_seconds, default_seconds, expected
):
    monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", max_seconds)
    monkeypatch.setattr(settings, "DEFAULT_EXECUTION_TIMEOUT", default_seconds)

    assert effective_execution_timeout(requested_seconds) == expected


@pytest.fixture
def unconfined_execution(tmp_path, monkeypatch):
    """Run the child without launcher.py, with the shared libraries importable."""
    monkeypatch.setattr(chain_mod, "abi_version", lambda: 0)
    monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "false")
    monkeypatch.setattr(settings, "BLOCK_NETWORK", False)
    shared_libs_path = copy_shared_libs_into_jail(tmp_path)
    real_build_base_env = chain_mod.build_base_env
    monkeypatch.setattr(
        chain_mod,
        "build_base_env",
        lambda python_executable: {
            **real_build_base_env(python_executable),
            "PYTHONPATH": str(shared_libs_path),
        },
    )


def _context(tmp_path: Path, code: str, requested_timeout: float | None) -> dict[str, Any]:
    return make_execute_context(
        tmp_path,
        python_executable=sys.executable,
        execution_id="exec-requested-timeout",
        code=code,
        secrets={},
        requested_timeout=requested_timeout,
    )


def _run_bounded(context: dict[str, Any]):
    async def runner():
        return await asyncio.wait_for(
            ExecuteCodeHandler().handle(context), timeout=RUN_BOUND_SECONDS
        )

    return asyncio.run(runner())


@pytest.mark.usefixtures("unconfined_execution")
@pytest.mark.parametrize(
    ("requested_seconds", "max_seconds", "default_seconds"),
    [(1, LONG_SECONDS, LONG_SECONDS), (LONG_SECONDS, 1, LONG_SECONDS), (None, LONG_SECONDS, 1)],
    ids=["requested", "requested-capped-at-maximum", "default"],
)
def test_killed_run_names_the_applied_timeout(
    tmp_path, monkeypatch, requested_seconds, max_seconds, default_seconds
):
    monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", max_seconds)
    monkeypatch.setattr(settings, "DEFAULT_EXECUTION_TIMEOUT", default_seconds)

    result = _run_bounded(_context(tmp_path, HANGING_CODE, requested_timeout=requested_seconds))

    assert result.returncode == 124
    assert result.stderr.endswith("Execution exceeded 1 seconds and was terminated.")


@pytest.mark.usefixtures("unconfined_execution")
def test_run_finishing_within_the_timeout_is_not_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", LONG_SECONDS)

    result = _run_bounded(_context(tmp_path, FINISHING_CODE, requested_timeout=5))

    assert result.returncode == 0, result.stderr
    assert "terminated" not in result.stderr


class _RecordingHandler(AbstractHandler):
    context: dict[str, Any] | None = None

    async def handle(self, context: dict[str, Any]):
        self.context = context
        return "recorded"


@pytest.mark.parametrize("timeout", [90.0, None], ids=["requested", "not-requested"])
def test_chain_hands_the_task_timeout_to_the_handlers(tmp_path, timeout):
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "output", base_venv_path=tmp_path / "venvs"
    )
    recording_handler = _RecordingHandler()
    chain.chain = recording_handler

    asyncio.run(
        chain.run(
            libraries=[],
            venv_name="default",
            execution_id="exec-chain-timeout",
            code=FINISHING_CODE,
            timeout=timeout,
        )
    )

    assert recording_handler.context["requested_timeout"] == timeout
