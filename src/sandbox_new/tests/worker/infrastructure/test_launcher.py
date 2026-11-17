"""What the launcher tells the user when a restriction it was asked for can't be applied.

The launcher runs as a script with its own directory on ``sys.path``, so it is imported
the same way here. The kernel calls are replaced: whether the host kernel supports a
restriction is not what is under test, only that a failure stops the run with the one
fixed sentence and never execs the job's code.
"""

import json
import sys
from pathlib import Path

import pytest

ISOLATION_DIR = Path(__file__).parents[3] / "worker" / "infrastructure" / "isolation"
# Only for the import: the rest of the session must not resolve other modules here.
sys.path.insert(0, str(ISOLATION_DIR))
try:
    import launcher
finally:
    sys.path.remove(str(ISOLATION_DIR))

UNSAFE = "This server can't run code safely right now, so the code wasn't run."
JAIL = {"read_write": [], "read_only": [], "read_exec": []}


def refuse(error_type: type[Exception]):
    def apply(*args, **kwargs):
        raise error_type("raw kernel detail")

    return apply


@pytest.fixture
def exec_calls(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher.os, "execv", lambda path, argv: calls.append(argv))
    return calls


def run_launcher(monkeypatch, plan: dict) -> None:
    monkeypatch.setattr(
        sys, "argv", ["launcher.py", json.dumps(plan), "/venv/bin/python", "/exec/code.py"]
    )
    launcher.main()


@pytest.mark.parametrize(
    "error_type",
    [
        launcher.landlock.LandlockUnavailableError,
        launcher.landlock.LandlockNetworkUnavailableError,
        launcher.landlock.LandlockSignalIsolationUnavailableError,
    ],
)
def test_a_jail_that_cannot_be_applied_stops_the_run_with_the_fixed_text(
    monkeypatch, capsys, exec_calls, error_type
):
    monkeypatch.setattr(launcher.landlock, "apply", refuse(error_type))

    with pytest.raises(SystemExit) as exited:
        run_launcher(
            monkeypatch,
            {"jail": JAIL, "network": {"mode": "unrestricted"}, "isolate_signals": True},
        )

    assert exited.value.code == 1
    assert capsys.readouterr().err.strip() == UNSAFE
    assert exec_calls == []


def test_a_network_block_that_cannot_be_applied_stops_the_run_with_the_fixed_text(
    monkeypatch, capsys, exec_calls
):
    monkeypatch.setattr(
        launcher.seccomp, "block_network", refuse(launcher.seccomp.SeccompUnavailableError)
    )

    with pytest.raises(SystemExit) as exited:
        run_launcher(
            monkeypatch, {"jail": None, "network": {"mode": "block_all"}, "isolate_signals": False}
        )

    assert exited.value.code == 1
    assert capsys.readouterr().err.strip() == UNSAFE
    assert exec_calls == []
