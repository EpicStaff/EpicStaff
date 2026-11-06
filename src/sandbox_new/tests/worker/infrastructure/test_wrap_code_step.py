"""Behavior of the step that writes the wrapped source to the execution's code file.

What the written source does when it runs is pinned by test_code_wrapper.py; here only
that the step writes it, as valid Python, for a run with and without storage.
"""

import pytest

from worker.infrastructure.execution.steps import WrapCodeStep
from tests.builders import make_context, make_worker_job


@pytest.mark.parametrize("use_storage", [False, True], ids=["without-storage", "with-storage"])
async def test_the_wrap_step_writes_source_that_compiles_to_the_code_file(tmp_path, use_storage):
    context = make_context(
        make_worker_job(
            code="def main(value):\n    return {'echo': value}",
            func_kwargs={"value": "x"},
            use_storage=use_storage,
            storage_org_prefix="org1" if use_storage else None,
        ),
        code_path=tmp_path / "code.py",
        result_file_path=tmp_path / "output.txt",
        failure_file_path=tmp_path / "failure.json",
        storage_mutations_path=tmp_path / "storage_mutations.json" if use_storage else None,
    )

    await WrapCodeStep()(context)

    compile((tmp_path / "code.py").read_text(encoding="utf-8"), "code.py", "exec")


async def test_each_run_gets_its_own_result_write_marker(tmp_path):
    markers = []
    for run in ("first", "second"):
        context = make_context(
            make_worker_job(),
            code_path=tmp_path / f"{run}.py",
            result_file_path=tmp_path / f"{run}-output.txt",
            failure_file_path=tmp_path / f"{run}-failure.json",
        )

        await WrapCodeStep()(context)

        markers.append(context.result_write_marker)

    assert all(markers)
    assert markers[0] != markers[1]
