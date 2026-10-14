"""Wiring coverage for ExecuteCodeHandler's isolation plan: the network
restriction, the Landlock signal isolation decision and the refusal when the
private-network egress firewall is required but not installed.

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
import egress_firewall
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


async def _run(
    tmp_path,
    monkeypatch,
    *,
    abi: int,
    block_network: bool = False,
    use_storage: bool = False,
    require_signal_isolation: bool = False,
    require_isolation: bool = True,
    block_private_network: bool = False,
    firewall_active: bool = False,
):
    """Run the handler on a kernel with Landlock `abi` under the given settings.

    Returns the result and the launcher plan, or None when nothing was spawned.
    """
    monkeypatch.setattr(settings, "BLOCK_NETWORK", block_network)
    monkeypatch.setattr(settings, "STORAGE_PORT", "9000")
    monkeypatch.setattr(settings, "REQUIRE_SIGNAL_ISOLATION", require_signal_isolation)
    monkeypatch.setattr(settings, "BLOCK_PRIVATE_NETWORK", block_private_network)
    monkeypatch.setenv("SANDBOX_REQUIRE_ISOLATION", "true" if require_isolation else "false")
    monkeypatch.setattr(egress_firewall, "is_active", lambda: firewall_active)
    monkeypatch.setattr(dynamic_venv_executor_chain, "abi_version", lambda: abi)
    recorded: dict = {}
    context = _make_execute_context(
        tmp_path,
        use_storage=use_storage,
        temp_storage_access_key="scoped-ak",
        temp_storage_secret_key="scoped-sk",
    )
    _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

    result = await ExecuteCodeHandler().handle(context)

    if "argv" not in recorded:
        return result, None
    if str(recorded["argv"][1]) != str(LAUNCHER_PATH):
        return result, "unconfined"
    return result, _plan_from_argv(recorded["argv"])


JAILED = "jailed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings_for_run", "expected_plan"),
    [
        ({"abi": 4}, {"jail": JAILED, "network": {"mode": "unrestricted"}, "isolate_signals": False}),
        (
            {"abi": 4, "block_network": True},
            {"jail": JAILED, "network": {"mode": "block_all"}, "isolate_signals": False},
        ),
        (
            {"abi": 4, "block_network": True, "use_storage": True},
            {"jail": JAILED, "network": {"mode": "allow_ports", "ports": [9000]}, "isolate_signals": False},
        ),
        # No Landlock but the network block requested: the launcher still runs, for seccomp.
        (
            {"abi": 0, "block_network": True, "require_isolation": False},
            {"jail": None, "network": {"mode": "block_all"}, "isolate_signals": False},
        ),
        # Signal isolation is enforced wherever the kernel supports it, required or not.
        (
            {"abi": 6, "require_signal_isolation": True},
            {"jail": JAILED, "network": {"mode": "unrestricted"}, "isolate_signals": True},
        ),
        (
            {"abi": 6, "require_signal_isolation": False},
            {"jail": JAILED, "network": {"mode": "unrestricted"}, "isolate_signals": True},
        ),
        (
            {"abi": 5, "require_signal_isolation": False},
            {"jail": JAILED, "network": {"mode": "unrestricted"}, "isolate_signals": False},
        ),
        (
            {"abi": 6, "block_network": True, "use_storage": True, "require_signal_isolation": True},
            {"jail": JAILED, "network": {"mode": "allow_ports", "ports": [9000]}, "isolate_signals": True},
        ),
        # The isolation opt-out at ABI 0 is not overridden by the signal isolation requirement.
        ({"abi": 0, "require_isolation": False, "require_signal_isolation": True}, "unconfined"),
        ({"abi": 6, "block_private_network": True, "firewall_active": True},
         {"jail": JAILED, "network": {"mode": "unrestricted"}, "isolate_signals": True}),
    ],
    ids=[
        "network-unrestricted",
        "network-blocked",
        "network-blocked-except-storage",
        "no-landlock-network-blocked",
        "signal-isolation-required-and-supported",
        "signal-isolation-supported-not-required",
        "old-kernel-signal-isolation-not-required",
        "storage-port-and-signal-isolation",
        "no-landlock-isolation-opted-out",
        "private-network-firewall-installed",
    ],
)
async def test_launcher_receives_the_plan_for_the_settings(
    tmp_path, monkeypatch, settings_for_run, expected_plan
):
    result, plan = await _run(tmp_path, monkeypatch, **settings_for_run)

    assert result.returncode == 0
    if isinstance(expected_plan, dict) and expected_plan["jail"] == JAILED:
        assert plan["jail"] is not None
        plan = {**plan, "jail": JAILED}
    assert plan == expected_plan


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings_for_run", "must_say", "must_not_say"),
    [
        (
            {"abi": 3, "block_network": True, "use_storage": True},
            ("Landlock ABI 4", "SANDBOX_BLOCK_NETWORK"),
            (),
        ),
        ({"abi": 5, "require_signal_isolation": True}, ("Landlock ABI 6+ (Linux 6.12+)", "SANDBOX_REQUIRE_SIGNAL_ISOLATION"), ()),
        # Without Landlock the filesystem isolation refusal is the one reported.
        ({"abi": 0, "require_signal_isolation": True}, ("kernel lacks Landlock",), ("SANDBOX_REQUIRE_SIGNAL_ISOLATION",)),
        *[
            # Both refuse; signal isolation is checked first.
            (
                {"abi": abi, "block_network": True, "use_storage": True, "require_signal_isolation": True},
                ("SANDBOX_REQUIRE_SIGNAL_ISOLATION",),
                ("SANDBOX_BLOCK_NETWORK",),
            )
            for abi in (1, 2, 3)
        ],
        (
            {"abi": 6, "block_private_network": True, "firewall_active": False},
            ("private-network isolation unavailable", "SANDBOX_BLOCK_PRIVATE_NETWORK=false"),
            (),
        ),
    ],
    ids=[
        "storage-port-needs-abi-4",
        "signal-isolation-needs-abi-6",
        "no-landlock",
        "abi-1-signal-before-network",
        "abi-2-signal-before-network",
        "abi-3-signal-before-network",
        "private-network-firewall-missing",
    ],
)
async def test_unsafe_settings_refuse_with_one_line_and_spawn_nothing(
    tmp_path, monkeypatch, settings_for_run, must_say, must_not_say
):
    result, plan = await _run(tmp_path, monkeypatch, **settings_for_run)

    assert plan is None
    assert result.returncode == 1
    assert result.stdout == ""
    assert "\n" not in result.stderr
    assert all(fragment in result.stderr for fragment in must_say)
    assert not any(fragment in result.stderr for fragment in must_not_say)


@pytest.mark.asyncio
async def test_running_without_signal_isolation_is_logged_as_a_warning(
    tmp_path, monkeypatch, warnings_logged
):
    await _run(tmp_path, monkeypatch, abi=5, require_signal_isolation=False)

    assert any("UNISOLATED" in message for message in warnings_logged)
