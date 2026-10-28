"""Behavior of the two capture steps.

The result step is the last step of every run, so it always completes the context. The
mutations step must never fail a run that already succeeded -- a broken mutations file is
a reporting problem, not an execution failure.
"""

import json

from worker.infrastructure.execution.steps import CaptureMutationsStep, CaptureResultStep
from tests.builders import make_context, make_worker_job

MAX_BYTES = 1024


async def test_a_clean_run_reads_its_result_file(tmp_path):
    result_file = tmp_path / "output.txt"
    result_file.write_text('{"echo": "x"}', encoding="utf-8")
    context = make_context(returncode=0, result_file_path=result_file)

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.result_data == '{"echo": "x"}'
    assert context.completed is True


async def test_a_failed_run_does_not_read_a_result(tmp_path):
    result_file = tmp_path / "output.txt"
    result_file.write_text("stale", encoding="utf-8")
    context = make_context(returncode=1, result_file_path=result_file)

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.result_data is None
    assert context.completed is True


async def test_a_missing_result_file_does_not_raise(tmp_path):
    context = make_context(returncode=0, result_file_path=tmp_path / "never-written.txt")

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.result_data is None
    assert context.completed is True


async def test_a_result_file_replaced_by_a_symlink_fails_the_run_without_reading_it(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("root-only secret", encoding="utf-8")
    result_file = tmp_path / "exec" / "output.txt"
    result_file.parent.mkdir()
    result_file.symlink_to(outside)
    context = make_context(returncode=0, result_file_path=result_file)

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.result_data is None
    assert context.completed is True
    assert context.returncode == 1
    assert "symbolic link" in context.stderr
    assert "root-only secret" not in context.stderr
    assert str(outside) not in context.stderr


async def test_a_result_file_over_the_configured_cap_fails_the_run(tmp_path):
    result_file = tmp_path / "output.txt"
    result_file.write_text("12345", encoding="utf-8")
    context = make_context(returncode=0, result_file_path=result_file)

    await CaptureResultStep(max_bytes=4)(context)

    assert context.result_data is None
    assert context.returncode == 1
    assert "larger than 4 bytes" in context.stderr


async def test_the_result_step_completes_even_without_a_result_path():
    context = make_context(returncode=0)

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.completed is True


def storage_context(tmp_path, *, returncode=0, use_storage=True, mutations=None):
    path = tmp_path / "storage_mutations.json"
    if mutations is not None:
        path.write_text(json.dumps(mutations), encoding="utf-8")
    return make_context(
        make_worker_job(use_storage=use_storage, storage_org_prefix="org1", session_id=7),
        returncode=returncode,
        storage_mutations_path=path,
    )


async def test_reported_mutations_are_recorded(tmp_path):
    context = storage_context(tmp_path, mutations=[{"path": "docs/a.txt", "action": "put"}])

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations.org_prefix == "org1"
    assert context.storage_mutations.session_id == 7
    assert context.storage_mutations.execution_id == "exec-1"
    assert context.storage_mutations.mutations == [{"path": "docs/a.txt", "action": "put"}]


async def test_a_job_without_storage_reports_nothing(tmp_path):
    context = storage_context(tmp_path, use_storage=False, mutations=[{"path": "a.txt"}])

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None


async def test_a_failed_run_reports_no_mutations(tmp_path):
    context = storage_context(tmp_path, returncode=1, mutations=[{"path": "a.txt"}])

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None


async def test_a_missing_mutations_file_reports_nothing(tmp_path):
    context = storage_context(tmp_path, mutations=None)

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None


async def test_an_empty_mutation_list_reports_nothing(tmp_path):
    context = storage_context(tmp_path, mutations=[])

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None


async def test_a_malformed_mutations_file_does_not_fail_a_successful_run(tmp_path):
    path = tmp_path / "storage_mutations.json"
    path.write_text("{not json", encoding="utf-8")
    context = make_context(
        make_worker_job(use_storage=True, storage_org_prefix="org1"),
        returncode=0,
        storage_mutations_path=path,
    )

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None
    assert context.completed is False
    assert context.returncode == 0


async def test_no_mutations_path_reports_nothing():
    context = make_context(
        make_worker_job(use_storage=True, storage_org_prefix="org1"), returncode=0
    )

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None


async def test_a_mutations_file_replaced_by_a_symlink_fails_the_run_without_reading_it(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"path": "other-org/a.txt", "action": "delete"}]))
    context = storage_context(tmp_path, mutations=None)
    context.storage_mutations_path.symlink_to(outside)

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None
    assert context.completed is True
    assert context.returncode == 1
    assert "symbolic link" in context.stderr
    assert str(outside) not in context.stderr


async def test_a_mutations_file_over_the_configured_cap_fails_the_run(tmp_path):
    context = storage_context(tmp_path, mutations=[{"path": "docs/a.txt", "action": "put"}])

    await CaptureMutationsStep(max_bytes=4)(context)

    assert context.storage_mutations is None
    assert context.returncode == 1
    assert "larger than 4 bytes" in context.stderr
