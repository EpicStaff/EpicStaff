"""Behavior of the workspace preparation step.

Every execution gets its own writable workspace and nothing writable is shared between
runs. The environment handed to the child is built here and deliberately does not inherit
the worker's own.
"""

import json

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.infrastructure.execution.steps import PrepareWorkspaceStep
from worker.infrastructure.execution.steps import prepare_workspace as prepare_workspace_module
from worker.infrastructure.execution.privileges import SANDBOX_GID, SANDBOX_UID
from tests.builders import make_context, make_worker_job, write_executable


def build_context(tmp_path, **job_fields):
    python_executable = write_executable(tmp_path / "venvs" / "venv-1abc" / "bin" / "python")
    return make_context(make_worker_job(**job_fields), python_executable=python_executable)


def build_step(tmp_path) -> PrepareWorkspaceStep:
    return PrepareWorkspaceStep(executions_dir=tmp_path / "executions")


async def test_the_execution_workspace_is_created(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert exec_dir.is_dir()
    assert (exec_dir / "home").is_dir()
    assert (exec_dir / "tmp").is_dir()
    assert (exec_dir / "work").is_dir()


async def test_the_workspace_paths_are_recorded_on_the_context(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert context.exec_dir == exec_dir
    assert context.home_dir == exec_dir / "home"
    assert context.tmp_dir == exec_dir / "tmp"
    assert context.work_dir == exec_dir / "work"
    assert context.code_path == exec_dir / "code.py"
    assert context.result_file_path == exec_dir / "output.txt"


async def test_the_child_environment_points_home_and_tmp_into_the_workspace(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert context.env["HOME"] == str(exec_dir / "home")
    assert context.env["TMPDIR"] == str(exec_dir / "tmp")


async def test_as_root_every_workspace_dir_is_handed_to_the_sandbox_user(tmp_path, monkeypatch):
    # A non-root test process cannot chown to another uid, so the chown itself is recorded.
    chowned = []
    monkeypatch.setattr(prepare_workspace_module, "can_drop_privileges", lambda: True)
    monkeypatch.setattr(
        prepare_workspace_module.os,
        "chown",
        lambda path, uid, gid: chowned.append((path, uid, gid)),
    )
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert context.completed is False
    assert sorted(chowned) == sorted(
        (path, SANDBOX_UID, SANDBOX_GID)
        for path in (exec_dir, exec_dir / "home", exec_dir / "tmp", exec_dir / "work")
    )


async def test_a_workspace_whose_chown_failed_is_still_removed_after_the_run(
    tmp_path, monkeypatch, result_sink
):
    def refuse_chown(path, uid, gid):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(prepare_workspace_module, "can_drop_privileges", lambda: True)
    monkeypatch.setattr(prepare_workspace_module.os, "chown", refuse_chown)
    orchestrator = ExecutionOrchestrator(
        Pipeline().register(build_step(tmp_path)), result_sink=result_sink, mask_secrets=True
    )

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, _ = result_sink.sent[0]
    assert result.returncode == 1
    assert "could not chown execution dirs" in result.stderr
    assert not (tmp_path / "executions" / "exec-1").exists()


async def test_secrets_reach_the_child_as_json(tmp_path):
    context = build_context(tmp_path, secrets={"TOKEN": "s3cret"})

    await build_step(tmp_path)(context)

    assert json.loads(context.env["EPICSTAFF_SECRETS"]) == {"TOKEN": "s3cret"}


async def test_a_job_without_secrets_still_gets_the_variable(tmp_path):
    context = build_context(tmp_path, secrets={})

    await build_step(tmp_path)(context)

    assert json.loads(context.env["EPICSTAFF_SECRETS"]) == {}


async def test_the_path_starts_with_the_venv_bin_directory(tmp_path):
    context = build_context(tmp_path)

    await build_step(tmp_path)(context)

    assert context.env["PATH"].split(":")[0] == str(tmp_path / "venvs" / "venv-1abc" / "bin")


async def test_running_over_an_existing_workspace_does_not_fail(tmp_path):
    (tmp_path / "executions" / "exec-1" / "home").mkdir(parents=True)
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    assert context.completed is False
    assert context.exec_dir.is_dir()
