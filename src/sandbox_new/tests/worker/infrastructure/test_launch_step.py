"""Behavior of the launch step.

The successful and timed-out paths run real child interpreters: ``landlock_abi=0`` with
an unrestricted network, so the launcher is bypassed. The launcher itself installs
kernel-dependent filters and is out of scope for this suite. Only the branch where the
child cannot be killed at all uses a stand-in -- a real process cannot reproduce it.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

from worker.domain.enums import NetworkPolicy
from worker.infrastructure.execution.steps import launch as launch_module
from worker.infrastructure.execution.steps import LaunchStep
from worker.infrastructure.execution.steps.launch import effective_timeout
from tests.builders import make_context, make_isolation_plan, make_worker_job
from tests.fakes import FakeProcess


def launchable(tmp_path, source: str, **job_fields):
    """A context ready for the launch step, with the given child source written out."""
    code_path = tmp_path / "code.py"
    code_path.write_text(source, encoding="utf-8")
    savefiles = tmp_path / "savefiles"
    savefiles.mkdir(exist_ok=True)
    return make_context(
        make_worker_job(**job_fields),
        python_executable=Path(sys.executable),
        code_path=code_path,
        savefiles_root=savefiles,
        isolation=make_isolation_plan(),
    )


async def test_a_successful_child_reports_its_output_and_return_code(tmp_path):
    context = launchable(tmp_path, "print('hello from the child')\n")

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 0
    assert "hello from the child" in context.stdout
    assert context.stderr == ""


async def test_a_failing_child_reports_its_return_code_and_stderr(tmp_path):
    context = launchable(tmp_path, "import sys\nprint('bad', file=sys.stderr)\nsys.exit(3)\n")

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 3
    assert "bad" in context.stderr


async def test_the_child_runs_in_the_savefiles_directory(tmp_path):
    context = launchable(tmp_path, "import os\nprint(os.getcwd())\n")

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.stdout.strip() == str(tmp_path / "savefiles")


async def test_the_child_gets_only_the_prepared_environment(tmp_path):
    context = launchable(tmp_path, "import os\nimport json\nprint(json.dumps(dict(os.environ)))\n")
    context.env = {"ONLY": "this"}

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    import json

    child_environment = json.loads(context.stdout)
    assert child_environment.get("ONLY") == "this"
    assert "SANDBOX_DB_PASSWORD" not in child_environment


async def test_a_fully_blocked_network_is_marked_in_the_child_environment(tmp_path):
    context = launchable(tmp_path, "import os\nprint(os.environ.get('SANDBOX_NETWORK_BLOCKED'))\n")
    context.isolation = make_isolation_plan(policy=NetworkPolicy.BLOCK_ALL)

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.stdout.strip() == "all"


async def test_a_storage_only_network_is_marked_in_the_child_environment(tmp_path):
    context = launchable(tmp_path, "import os\nprint(os.environ.get('SANDBOX_NETWORK_BLOCKED'))\n")
    context.isolation = make_isolation_plan(
        landlock_abi=5, policy=NetworkPolicy.ALLOW_PORTS, allowed_tcp_ports=(9000,)
    )

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.stdout.strip() == "storage_only"


async def test_an_unrestricted_network_sets_no_marker(tmp_path):
    context = launchable(tmp_path, "import os\nprint(os.environ.get('SANDBOX_NETWORK_BLOCKED'))\n")

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.stdout.strip() == "None"


async def test_a_hanging_child_is_terminated_and_reported_as_a_timeout(tmp_path):
    context = launchable(tmp_path, "import time\ntime.sleep(30)\n", timeout=0.2)

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 124
    assert "exceeded 0.2 seconds and was terminated" in context.stderr


async def test_the_per_job_timeout_overrides_the_configured_default(tmp_path):
    context = launchable(tmp_path, "import time\ntime.sleep(30)\n", timeout=0.2)

    await LaunchStep(default_timeout=600, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 124


async def test_the_configured_default_applies_when_the_job_sets_no_timeout(tmp_path):
    context = launchable(tmp_path, "import time\ntime.sleep(30)\n", timeout=None)

    await LaunchStep(default_timeout=0.2, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 124
    assert "exceeded 0.2 seconds" in context.stderr


async def test_a_child_that_cannot_be_killed_is_reported_as_possibly_still_running(
    tmp_path, monkeypatch
):
    process = FakeProcess(hang=True, kill_error=PermissionError(1, "Operation not permitted"))

    async def fake_create_subprocess_exec(*argv, **kwargs):
        return process

    def refuse_killpg(pgid, signal_number):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(launch_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(launch_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(launch_module.os, "killpg", refuse_killpg)

    context = launchable(tmp_path, "", timeout=0.1)

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert context.returncode == 124
    assert "may still be running" in context.stderr
    assert process.kill_calls == 1


@pytest.mark.parametrize(
    ("source", "timeout", "returncode", "timed_out"),
    [
        ("print('ok')\n", None, 0, False),
        ("import sys\nsys.exit(3)\n", None, 3, False),
        ("import time\ntime.sleep(30)\n", 0.2, 124, True),
    ],
    ids=["success", "code-failed", "timed-out"],
)
async def test_the_child_logs_exec_launched_and_exec_exited(
    tmp_path, checkpoints, source, timeout, returncode, timed_out
):
    context = launchable(tmp_path, source, execution_id="exec-9", session_id=4, timeout=timeout)

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=None)(context)

    assert checkpoints == [
        {"checkpoint": "exec_launched", "session_id": 4, "execution_id": "exec-9"},
        {
            "checkpoint": "exec_exited",
            "session_id": 4,
            "execution_id": "exec-9",
            "returncode": returncode,
            "timed_out": timed_out,
        },
    ]


def test_argv_without_isolation_runs_the_child_directly():
    argv = LaunchStep._build_argv(
        isolation=make_isolation_plan(),
        python_executable=Path("/venvs/venv-1abc/bin/python"),
        code_path=Path("/executions/exec-1/code.py"),
    )

    assert argv == ["/venvs/venv-1abc/bin/python", "/executions/exec-1/code.py"]


def test_argv_with_landlock_wraps_the_child_in_the_launcher():
    import json

    from worker.domain.models import Jail

    jail = Jail(read_write=("/exec",), read_only=("/etc/hosts",), read_exec=("/usr",))
    argv = LaunchStep._build_argv(
        isolation=make_isolation_plan(
            landlock_abi=6, policy=NetworkPolicy.BLOCK_ALL, isolate_signals=True, jail=jail
        ),
        python_executable=Path("/venvs/venv-1abc/bin/python"),
        code_path=Path("/executions/exec-1/code.py"),
    )

    assert argv[0] == sys.executable
    assert argv[1].endswith("launcher.py")
    assert argv[3:] == ["/venvs/venv-1abc/bin/python", "/executions/exec-1/code.py"]
    assert json.loads(argv[2]) == {
        "jail": {
            "read_write": ["/exec"],
            "read_only": ["/etc/hosts"],
            "read_exec": ["/usr"],
        },
        "network": {"mode": "block_all"},
        "isolate_signals": True,
    }


def test_argv_carries_the_allowed_ports_for_a_storage_execution():
    import json

    argv = LaunchStep._build_argv(
        isolation=make_isolation_plan(
            landlock_abi=5, policy=NetworkPolicy.ALLOW_PORTS, allowed_tcp_ports=(9000,)
        ),
        python_executable=Path("/venvs/venv-1abc/bin/python"),
        code_path=Path("/executions/exec-1/code.py"),
    )

    plan = json.loads(argv[2])
    assert plan["network"] == {"mode": "allow_ports", "ports": [9000]}
    assert plan["jail"] is None


def test_argv_wraps_a_blocked_network_even_without_landlock():
    argv = LaunchStep._build_argv(
        isolation=make_isolation_plan(landlock_abi=0, policy=NetworkPolicy.BLOCK_ALL),
        python_executable=Path("/venvs/venv-1abc/bin/python"),
        code_path=Path("/executions/exec-1/code.py"),
    )

    assert argv[1].endswith("launcher.py")


@pytest.mark.parametrize(
    ("requested", "minimum", "maximum", "default", "expected"),
    [
        (30, 3, 300, 60, 30),
        (300, 3, 300, 60, 300),
        (600, 3, 300, 60, 300),
        (1, 3, 300, 60, 3),
        (0, 3, 300, 60, 3),
        (None, 3, 300, 60, 60),
        (None, 3, 30, 60, 30),
        (600, 3, None, 60, 600),
        (1, 3, None, 60, 3),
        (None, 3, None, 60, 60),
    ],
    ids=[
        "requested-below-maximum",
        "requested-equal-to-maximum",
        "requested-above-maximum-is-capped",
        "requested-below-minimum-is-raised",
        "requested-zero-is-raised-to-the-minimum",
        "not-requested-takes-the-default",
        "default-above-maximum-is-capped",
        "no-maximum-keeps-the-request",
        "no-maximum-still-applies-the-minimum",
        "no-maximum-not-requested-takes-the-default",
    ],
)
def test_effective_timeout(requested, minimum, maximum, default, expected):
    assert (
        effective_timeout(requested, default=default, minimum=minimum, maximum=maximum)
        == expected
    )


async def test_a_requested_timeout_above_the_maximum_is_the_one_actually_applied(tmp_path):
    """The cap is not advisory: the child is killed at the maximum, not at what it asked for."""
    context = launchable(tmp_path, "import time\ntime.sleep(30)\n", timeout=25)

    await LaunchStep(default_timeout=30, min_timeout=0, max_timeout=0.2)(context)

    assert context.returncode == 124
    assert "exceeded 0.2 seconds and was terminated" in context.stderr
