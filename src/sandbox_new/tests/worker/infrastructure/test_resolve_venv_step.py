"""Behavior of the venv resolution step.

Defense in depth, not the readiness gate: the manager already waits for the build. This
step only refuses to launch against a path that is not there.
"""

from worker.infrastructure.execution.steps import ResolveVenvStep
from tests.builders import make_context, make_worker_job, write_executable


async def test_an_existing_venv_resolves_to_its_python_binary(tmp_path):
    write_executable(tmp_path / "venv-1abc" / "bin" / "python")
    context = make_context(make_worker_job(venv_hash="1abc"))

    await ResolveVenvStep(venvs_dir=tmp_path)(context)

    assert context.python_executable == tmp_path / "venv-1abc" / "bin" / "python"
    assert context.completed is False


async def test_a_missing_venv_fails_the_job(tmp_path):
    context = make_context(make_worker_job(venv_hash="missing"))

    await ResolveVenvStep(venvs_dir=tmp_path)(context)

    assert context.python_executable is None
    assert context.completed is True
    assert context.returncode == 1
    assert context.stderr == "Execution environment is not available."


async def test_a_venv_directory_without_a_python_binary_fails_the_job(tmp_path):
    (tmp_path / "venv-1abc").mkdir()
    context = make_context(make_worker_job(venv_hash="1abc"))

    await ResolveVenvStep(venvs_dir=tmp_path)(context)

    assert context.completed is True
    assert context.python_executable is None
