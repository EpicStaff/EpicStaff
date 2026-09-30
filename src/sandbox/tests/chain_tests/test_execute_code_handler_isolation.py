"""Wiring coverage for ExecuteCodeHandler's isolation plan: the network
restriction and the Landlock signal isolation decision.

Parent-side only, no real kernel confinement: `abi_version()`,
`settings.BLOCK_NETWORK` and `settings.REQUIRE_SIGNAL_ISOLATION` are
monkeypatched so every branch runs the same on any host, including kernels
without Landlock ABI 4 (Linux 6.7+) or ABI 6 (Linux 6.12+).
`asyncio.create_subprocess_exec` is faked to capture argv (same pattern as
test_execute_code_handler_storage.py) so tests can inspect the JSON plan
passed to launcher.py without spawning it.
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
from utils.logger import logger

from conftest import make_execute_context


def _make_execute_context(tmp_path: Path, **overrides):
    return make_execute_context(tmp_path, execution_id="test-exec-isolation", **overrides)


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


@pytest.fixture
def warnings_logged():
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]), level="WARNING"
    )
    yield messages
    logger.remove(handler_id)


async def _handle(tmp_path, monkeypatch, *, abi: int, require_signal_isolation: bool):
    """Run the handler with network blocking off, so only signal isolation varies."""
    monkeypatch.setattr(settings, "BLOCK_NETWORK", False)
    monkeypatch.setattr(settings, "REQUIRE_SIGNAL_ISOLATION", require_signal_isolation)
    monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: abi)

    recorded: dict = {}
    context = _make_execute_context(tmp_path)
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    result = await ExecuteCodeHandler().handle(context)
    return result, recorded


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


class TestSignalIsolationSupported:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("require_signal_isolation", [True, False])
    async def test_plan_always_enforces_signal_isolation(
        self, tmp_path, monkeypatch, require_signal_isolation
    ):
        result, recorded = await _handle(
            tmp_path, monkeypatch, abi=6, require_signal_isolation=require_signal_isolation
        )

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["isolate_signals"] is True
        assert plan["jail"] is not None


class TestSignalIsolationUnavailableAndRequired:
    @pytest.mark.asyncio
    async def test_refuses_with_one_stderr_line_without_spawning(self, tmp_path, monkeypatch):
        result, recorded = await _handle(
            tmp_path, monkeypatch, abi=5, require_signal_isolation=True
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert "Landlock ABI 6+ (Linux 6.12+)" in result.stderr
        assert "SANDBOX_REQUIRE_SIGNAL_ISOLATION" in result.stderr
        assert "\n" not in result.stderr
        assert "argv" not in recorded


class TestSignalIsolationUnavailableAndNotRequired:
    @pytest.mark.asyncio
    async def test_runs_unisolated_and_warns(self, tmp_path, monkeypatch, warnings_logged):
        result, recorded = await _handle(
            tmp_path, monkeypatch, abi=5, require_signal_isolation=False
        )

        assert result.returncode == 0
        plan = _plan_from_argv(recorded["argv"])
        assert plan["isolate_signals"] is False
        assert plan["jail"] is not None
        assert any("UNISOLATED" in message for message in warnings_logged)


class TestSignalIsolationWithoutLandlock:
    @pytest.mark.asyncio
    async def test_isolation_opt_out_is_not_overridden_by_the_signal_isolation_requirement(
        self, tmp_path, monkeypatch, warnings_logged
    ):
        """ABI 0 is governed by SANDBOX_REQUIRE_ISOLATION alone: with it off,
        the execution runs unconfined even though signal isolation is required."""
        monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "false")

        result, recorded = await _handle(
            tmp_path, monkeypatch, abi=0, require_signal_isolation=True
        )

        assert result.returncode == 0
        assert str(recorded["argv"][1]) != str(LAUNCHER_PATH)
        assert not any("UNISOLATED" in message for message in warnings_logged)

    @pytest.mark.asyncio
    async def test_isolation_refusal_is_the_one_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "true")

        result, recorded = await _handle(
            tmp_path, monkeypatch, abi=0, require_signal_isolation=True
        )

        assert result.returncode == 1
        assert "kernel lacks Landlock" in result.stderr
        assert "SANDBOX_REQUIRE_SIGNAL_ISOLATION" not in result.stderr
        assert "argv" not in recorded


class TestSignalIsolationWithNetworkBlockAndStorage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("abi", [1, 2, 3])
    async def test_signal_isolation_refusal_is_reported_before_the_network_refusal(
        self, tmp_path, monkeypatch, abi
    ):
        """Both decisions refuse here; the handler checks signal isolation first."""
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
        monkeypatch.setattr(settings, "REQUIRE_SIGNAL_ISOLATION", True)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: abi)

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
        assert "SANDBOX_REQUIRE_SIGNAL_ISOLATION" in result.stderr
        assert "SANDBOX_BLOCK_NETWORK" not in result.stderr
        assert "argv" not in recorded

    @pytest.mark.asyncio
    async def test_plan_carries_storage_port_and_signal_isolation_together(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(settings, "BLOCK_NETWORK", True)
        monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
        monkeypatch.setattr(settings, "REQUIRE_SIGNAL_ISOLATION", True)
        monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: 6)

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
        assert plan["isolate_signals"] is True
        assert plan["jail"] is not None
