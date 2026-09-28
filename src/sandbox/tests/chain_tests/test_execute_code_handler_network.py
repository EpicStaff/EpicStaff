"""Wiring coverage for ExecuteCodeHandler's network-restriction plan.

Parent-side only, no real kernel confinement: `abi_version()` and
`settings.BLOCK_NETWORK` are monkeypatched so this suite runs the same on any
host, including kernels without Landlock 6.7+. `asyncio.create_subprocess_exec`
is faked to capture argv (same pattern as test_execute_code_handler_storage.py)
so tests can inspect the JSON plan passed to launcher.py without spawning it.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
import settings
from dynamic_venv_executor_chain import LAUNCHER_PATH, ExecuteCodeHandler

from conftest import make_execute_context


def _make_execute_context(tmp_path: Path, **overrides):
    return make_execute_context(tmp_path, execution_id="test-exec-network", **overrides)


def _patch_subprocess(monkeypatch, recorded: dict, result_file_path: Path) -> None:
    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_create(*args, **kwargs):
        recorded["argv"] = args
        recorded.update(kwargs)
        result_file_path.write_text('"ok"')
        return _FakeProcess()

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        _fake_create,
    )


def _plan_from_argv(argv: tuple) -> dict:
    """argv is [sys.executable, launcher.py, <plan-json>, <venv-python>, <code-path>]."""
    assert str(LAUNCHER_PATH) == str(argv[1])
    return json.loads(argv[2])


class TestNetworkFlagOff:
    @pytest.mark.asyncio
    async def test_no_network_restriction_in_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", False)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(tmp_path)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["network"] == {"mode": "unrestricted"}
        assert plan["jail"] is not None


class TestNetworkFlagOnWithoutStorage:
    @pytest.mark.asyncio
    async def test_plan_blocks_all_inet_with_no_ports(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(tmp_path, use_storage=False)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["network"] == {"mode": "block_all"}


class TestNetworkFlagOnWithStorageSufficientAbi:
    @pytest.mark.asyncio
    async def test_plan_carries_storage_port_and_does_not_block_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 4)

        recorded: dict = {}
        context = _make_execute_context(
            tmp_path,
            use_storage=True,
            temp_storage_access_key="scoped-ak",
            temp_storage_secret_key="scoped-sk",
        )
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["network"] == {"mode": "allow_ports", "ports": [9000]}


class TestNetworkFlagOnWithStorageInsufficientAbi:
    @pytest.mark.asyncio
    async def test_refuses_without_spawning_a_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 3)

        recorded: dict = {}
        context = _make_execute_context(
            tmp_path,
            use_storage=True,
            temp_storage_access_key="scoped-ak",
            temp_storage_secret_key="scoped-sk",
        )
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 1
        assert "Landlock ABI 4" in result.stderr
        assert "SANDBOX_BLOCK_NETWORK" in result.stderr
        assert "argv" not in recorded


class TestNetworkFlagOnWithoutLandlockAndIsolationNotRequired:
    @pytest.mark.asyncio
    async def test_launcher_still_used_with_null_jail_and_block_all(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "false")
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 0)

        recorded: dict = {}
        context = _make_execute_context(tmp_path, use_storage=False)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        result = await ExecuteCodeHandler().handle(context)

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["jail"] is None
        assert plan["network"] == {"mode": "block_all"}
