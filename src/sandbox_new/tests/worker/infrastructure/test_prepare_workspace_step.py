"""Behavior of the workspace preparation step.

Every execution gets its own writable workspace; the shared savefiles volume is the one
writable area runs have in common. The environment handed to the child is built here and
deliberately does not inherit the worker's own.
"""

import json

from worker.infrastructure.execution.steps import PrepareWorkspaceStep
from tests.builders import make_context, make_worker_job, write_executable


def build_context(tmp_path, **job_fields):
    python_executable = write_executable(tmp_path / "venvs" / "venv-1abc" / "bin" / "python")
    return make_context(make_worker_job(**job_fields), python_executable=python_executable)


def build_step(tmp_path) -> PrepareWorkspaceStep:
    return PrepareWorkspaceStep(
        executions_dir=tmp_path / "executions", savefiles_root=tmp_path / "savefiles"
    )


async def test_the_execution_workspace_is_created(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert exec_dir.is_dir()
    assert (exec_dir / "home").is_dir()
    assert (exec_dir / "tmp").is_dir()
    assert (tmp_path / "savefiles").is_dir()


async def test_the_workspace_paths_are_recorded_on_the_context(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert context.exec_dir == exec_dir
    assert context.home_dir == exec_dir / "home"
    assert context.tmp_dir == exec_dir / "tmp"
    assert context.savefiles_root == tmp_path / "savefiles"
    assert context.code_path == exec_dir / "code.py"
    assert context.result_file_path == exec_dir / "output.txt"


async def test_the_child_environment_points_home_and_tmp_into_the_workspace(tmp_path):
    context = build_context(tmp_path, execution_id="exec-1")

    await build_step(tmp_path)(context)

    exec_dir = tmp_path / "executions" / "exec-1"
    assert context.env["HOME"] == str(exec_dir / "home")
    assert context.env["TMPDIR"] == str(exec_dir / "tmp")
    assert context.env["CONTAINER_SAVEFILES_PATH"] == str(tmp_path / "savefiles")


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
