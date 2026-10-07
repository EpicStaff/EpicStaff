"""launcher.main() wiring: plan -> landlock.apply() -> execv, and fail-closed
error handling.

`landlock.apply` and `os.execv` are replaced so the plan can be inspected
in-process without confining or replacing the pytest interpreter.
`seccomp.block_network` is stubbed too, so no plan can install a seccomp
filter into the pytest process. The kernel side of signal isolation is
covered in test_landlock.py.
"""

import json
import sys

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: Landlock is Linux-specific; runs in the Linux image",
)

import landlock
import launcher

_JAIL = {"read_write": ["/rw"], "read_only": ["/ro"], "read_exec": ["/rx"]}


class _ExecvCalled(Exception):
    pass


@pytest.fixture
def recorded(monkeypatch):
    calls: dict = {}

    def _fake_apply(**kwargs):
        calls["apply"] = kwargs

    def _fake_execv(path, argv):
        calls["execv"] = (path, argv)
        raise _ExecvCalled

    def _fake_block_network():
        calls["block_network"] = True

    monkeypatch.setattr(landlock, "apply", _fake_apply)
    monkeypatch.setattr(launcher.seccomp, "block_network", _fake_block_network)
    monkeypatch.setattr(launcher.os, "execv", _fake_execv)
    return calls


def _run_launcher(monkeypatch, plan: dict) -> None:
    monkeypatch.setattr(sys, "argv", ["launcher.py", json.dumps(plan), "/venv/python", "/code.py"])
    launcher.main()


class TestSignalIsolationReachesApply:
    @pytest.mark.parametrize("isolate_signals", [True, False])
    def test_signal_isolation_flag_from_the_plan_is_passed_to_apply(
        self, monkeypatch, recorded, isolate_signals
    ):
        plan = {"jail": _JAIL, "network": {"mode": "unrestricted"}, "isolate_signals": isolate_signals}

        with pytest.raises(_ExecvCalled):
            _run_launcher(monkeypatch, plan)

        assert recorded["apply"] == {
            "rw_paths": ["/rw"],
            "ro_paths": ["/ro"],
            "roexec_paths": ["/rx"],
            "allowed_tcp_ports": None,
            "isolate_signals": isolate_signals,
        }
        assert recorded["execv"] == ("/venv/python", ["/venv/python", "/code.py"])

    def test_signal_isolation_and_port_allowlist_are_passed_together(self, monkeypatch, recorded):
        plan = {
            "jail": _JAIL,
            "network": {"mode": "allow_ports", "ports": [9000]},
            "isolate_signals": True,
        }

        with pytest.raises(_ExecvCalled):
            _run_launcher(monkeypatch, plan)

        assert recorded["apply"]["allowed_tcp_ports"] == (9000,)
        assert recorded["apply"]["isolate_signals"] is True


class TestSignalIsolationUnavailable:
    def test_exits_1_with_one_stderr_line_and_never_execs(self, monkeypatch, recorded, capsys):
        def _raise(**kwargs):
            raise landlock.LandlockSignalIsolationUnavailableError("ABI 5 < 6")

        monkeypatch.setattr(landlock, "apply", _raise)
        plan = {"jail": _JAIL, "network": {"mode": "unrestricted"}, "isolate_signals": True}

        with pytest.raises(SystemExit) as exit_info:
            _run_launcher(monkeypatch, plan)

        assert exit_info.value.code == 1
        assert "execv" not in recorded
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "Sandbox isolation unavailable: Landlock signal isolation could not be applied.\n"
        )
