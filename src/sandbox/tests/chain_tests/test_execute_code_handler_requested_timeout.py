"""A task's requested execution timeout can only shorten the sandbox ceiling.

`CodeTaskData.timeout` comes from the node (or the panel test-run) and is
untrusted, so ExecuteCodeHandler applies `min(requested, SANDBOX_EXECUTION_TIMEOUT)`
and the ceiling alone when nothing was requested. A run killed for running past
that limit is reported with `timed_out=True` and the limit actually applied in
`effective_timeout_seconds`, so crew names the real limit rather than the one it
asked for. A run that finished reports neither.

The handler tests spawn a real hanging process, but without launcher.py: Landlock
is reported absent (`abi_version` -> 0) with isolation not required, so the child
runs unconfined. That keeps them independent of the uid the launcher needs, while
the timeout, the kill and the result are the real code paths.
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
# Long enough that only the requested timeout can end a hanging run inside the bound.
LONG_CEILING_SECONDS = 120
# Bounds every handler run so a timeout that is not applied fails the test instead of
# hanging the suite.
RUN_BOUND_SECONDS = 15


@pytest.mark.parametrize(
    ("requested_seconds", "ceiling_seconds", "expected"),
    [
        (30, 300, 30),
        (300, 300, 300),
        (600, 300, 300),
        (None, 300, 300),
        (30, None, 30),
        (None, None, None),
    ],
    ids=[
        "below-ceiling",
        "equal-to-ceiling",
        "above-ceiling-is-clamped",
        "not-requested-takes-ceiling",
        "no-ceiling-takes-request",
        "neither-is-unbounded",
    ],
)
def test_effective_execution_timeout(requested_seconds, ceiling_seconds, expected):
    assert (
        effective_execution_timeout(
            requested_seconds=requested_seconds, ceiling_seconds=ceiling_seconds
        )
        == expected
    )


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
class TestHandlerAppliesTheEffectiveTimeout:
    def test_requested_timeout_below_the_ceiling_kills_the_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", LONG_CEILING_SECONDS)

        result = _run_bounded(_context(tmp_path, HANGING_CODE, requested_timeout=1))

        assert result.returncode == 124
        assert result.timed_out is True
        assert result.effective_timeout_seconds == 1
        assert "Execution exceeded 1 seconds and was terminated." in result.stderr

    def test_requested_timeout_above_the_ceiling_is_cut_to_the_ceiling(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)

        result = _run_bounded(
            _context(tmp_path, HANGING_CODE, requested_timeout=LONG_CEILING_SECONDS)
        )

        assert result.returncode == 124
        assert result.timed_out is True
        assert result.effective_timeout_seconds == 1

    def test_no_requested_timeout_applies_the_ceiling(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", 1)

        result = _run_bounded(_context(tmp_path, HANGING_CODE, requested_timeout=None))

        assert result.timed_out is True
        assert result.effective_timeout_seconds == 1

    def test_finished_run_is_not_reported_as_timed_out(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "EXECUTION_TIMEOUT", LONG_CEILING_SECONDS)

        result = _run_bounded(_context(tmp_path, FINISHING_CODE, requested_timeout=5))

        assert result.returncode == 0, result.stderr
        assert result.timed_out is False
        assert result.effective_timeout_seconds is None


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
