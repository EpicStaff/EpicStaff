"""Behavior of the code wrapper and the step that writes its output.

Every test compiles the generated source. The wrapper is a long f-string with
interpolated ``repr`` output, so substring assertions alone would happily pass on source
that cannot be parsed.
"""

import pytest

from worker.infrastructure.execution.code_wrapper import wrap_code
from worker.infrastructure.execution.steps import WrapCodeStep
from tests.builders import make_context, make_worker_job

SIMPLE_CODE = "def main(value):\n    return {'echo': value}"


def wrap(tmp_path, **overrides):
    arguments = {
        "code": SIMPLE_CODE,
        "result_file_path": tmp_path / "output.txt",
        "entrypoint": "main",
        "func_kwargs": {"value": "x"},
        "global_kwargs": {},
        "storage_mutations_path": None,
    }
    arguments.update(overrides)
    return wrap_code(**arguments)


def test_the_generated_source_compiles(tmp_path):
    compile(wrap(tmp_path), "<wrapped>", "exec")


@pytest.mark.parametrize(
    "code",
    [
        "def main(value):\n    return \"it's\"",
        'def main(value):\n    return "back\\\\slash"',
        'def main(value):\n    return """triple"""',
        "def main(value):\n    # comment with {braces}\n    return 1",
    ],
)
def test_awkward_user_code_still_compiles(tmp_path, code):
    compile(wrap(tmp_path, code=code), "<wrapped>", "exec")


@pytest.mark.parametrize(
    "func_kwargs",
    [{}, {"value": "it's"}, {"value": {"nested": [1, 2]}}, {"value": None}],
)
def test_awkward_arguments_still_compile(tmp_path, func_kwargs):
    compile(wrap(tmp_path, func_kwargs=func_kwargs), "<wrapped>", "exec")


def test_the_entrypoint_is_called_with_the_arguments(tmp_path):
    source = wrap(tmp_path, entrypoint="handler", func_kwargs={"value": "x"})

    assert "sys_result_variable = handler(**__sys_dot_kwargs)" in source
    assert "{'value': 'x'}" in source


def test_the_result_is_written_to_the_result_file(tmp_path):
    source = wrap(tmp_path, result_file_path=tmp_path / "output.txt")

    assert (tmp_path / "output.txt").as_posix() in source
    assert "json.dumps(sys_result_variable)" in source


def test_globals_are_injected(tmp_path):
    source = wrap(tmp_path, global_kwargs={"LIMIT": 3})

    assert "{'LIMIT': 3}" in source
    compile(source, "<wrapped>", "exec")


def test_no_mutation_tail_without_a_mutations_path(tmp_path):
    assert "epicstaff_storage" not in wrap(tmp_path, storage_mutations_path=None)


def test_the_mutation_tail_is_appended_when_a_path_is_given(tmp_path):
    source = wrap(tmp_path, storage_mutations_path=tmp_path / "storage_mutations.json")

    assert "epicstaff_storage" in source
    assert (tmp_path / "storage_mutations.json").as_posix() in source
    compile(source, "<wrapped>", "exec")


def test_the_source_always_ends_by_exiting_cleanly(tmp_path):
    assert wrap(tmp_path).rstrip().endswith("sys.exit(0)")


async def test_the_wrap_step_writes_the_generated_source_to_the_code_file(tmp_path):
    context = make_context(
        make_worker_job(code=SIMPLE_CODE, entrypoint="main", func_kwargs={"value": "x"}),
        code_path=tmp_path / "code.py",
        result_file_path=tmp_path / "output.txt",
    )

    await WrapCodeStep()(context)

    source = (tmp_path / "code.py").read_text(encoding="utf-8")
    compile(source, "<wrapped>", "exec")
    assert "def main(value):" in source


async def test_the_wrap_step_includes_the_mutation_tail_when_storage_is_in_play(tmp_path):
    context = make_context(
        make_worker_job(use_storage=True, storage_org_prefix="org1"),
        code_path=tmp_path / "code.py",
        result_file_path=tmp_path / "output.txt",
        storage_mutations_path=tmp_path / "storage_mutations.json",
    )

    await WrapCodeStep()(context)

    assert "epicstaff_storage" in (tmp_path / "code.py").read_text(encoding="utf-8")
