"""Behavior of the two capture steps.

The result step is the last step of every run, so it always completes the context. The
mutations step must never fail a run that already succeeded -- a broken mutations file is
a reporting problem, not an execution failure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import settings

from worker.infrastructure.execution.code_wrapper import RESULT_WRITE_FAILED_EXIT_CODE
from worker.infrastructure.execution.steps import (
    CaptureMutationsStep,
    CaptureResultStep,
    WrapCodeStep,
)
from tests.builders import make_context, make_worker_job
from tests.public_errors import SERVER_ERROR, logged_with, reference_in

MAX_BYTES = 1024
MARKER = "5f0c2a9e7b1d4e6f8a3c0b2d9e4f7a1c"


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


async def test_a_result_file_replaced_by_a_symlink_fails_the_run_without_reading_it(
    tmp_path, error_logs
):
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
    reference = reference_in(SERVER_ERROR, context.stderr)
    log_line = logged_with(reference, error_logs)
    assert "symbolic link" in log_line
    assert "root-only secret" not in log_line
    assert str(outside) not in log_line


async def test_a_result_file_the_code_could_not_write_fails_as_a_server_error(
    tmp_path, error_logs
):
    write_error = "PermissionError: [Errno 13] Permission denied: '/srv/executions/exec-1/output.txt'"
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"printed by the user\n\n{MARKER}{write_error}\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.completed is True
    assert context.returncode == 1
    assert context.result_data is None
    user_output, public_text = context.stderr.split("\n")
    assert user_output == "printed by the user"
    reference = reference_in(SERVER_ERROR, public_text)
    assert write_error in logged_with(reference, error_logs)


async def test_a_result_file_write_error_alone_on_stderr_leaves_no_user_output(
    tmp_path, error_logs
):
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"\n{MARKER}OSError: [Errno 28] No space left on device\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    reference = reference_in(SERVER_ERROR, context.stderr)
    assert "No space left on device" in logged_with(reference, error_logs)


async def test_user_output_left_unfinished_stays_with_the_user(tmp_path, error_logs):
    write_error = "FileNotFoundError: [Errno 2] No such file or directory: '/srv/exec-1/output.txt'"
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"partial\n{MARKER}{write_error}\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    user_output, public_text = context.stderr.split("\n")
    assert user_output == "partial"
    reference = reference_in(SERVER_ERROR, public_text)
    assert write_error in logged_with(reference, error_logs)


async def test_a_multi_line_write_error_is_logged_whole_on_one_line_and_none_reaches_the_user(
    tmp_path, error_logs
):
    write_error = (
        "OSError: could not write '/srv/executions/exec-1/output.txt'\n"
        "2026-01-01 00:00:00 | ERROR | forged entry"
    )
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"printed by the user\n\n{MARKER}{write_error}\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    user_output, public_text = context.stderr.split("\n")
    assert user_output == "printed by the user"
    reference = reference_in(SERVER_ERROR, public_text)
    log_line = logged_with(reference, error_logs)
    assert (
        "OSError: could not write '/srv/executions/exec-1/output.txt'"
        "\\n2026-01-01 00:00:00 | ERROR | forged entry"
    ) in log_line
    assert "\n2026-01-01" not in log_line


async def test_the_user_echoing_the_marker_before_the_write_error_keeps_the_echo(
    tmp_path, error_logs
):
    write_error = "OSError: [Errno 28] No space left on device"
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"echo {MARKER}\n\n{MARKER}{write_error}\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    user_output, public_text = context.stderr.split("\n")
    assert user_output == f"echo {MARKER}"
    reference = reference_in(SERVER_ERROR, public_text)
    log_line = logged_with(reference, error_logs)
    assert f"result file: {write_error!r}" in log_line


async def test_the_users_own_exit_with_the_write_failure_code_is_an_ordinary_failure(
    tmp_path, error_logs
):
    user_stderr = "diagnostics\nsecond line\n"
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=user_stderr,
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    assert context.completed is True
    assert context.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert context.stderr == user_stderr
    assert context.result_data is None
    assert error_logs == []


async def test_text_written_past_the_marker_is_logged_cut_short(tmp_path, error_logs):
    context = make_context(
        returncode=RESULT_WRITE_FAILED_EXIT_CODE,
        stderr=f"\n{MARKER}" + "x" * 10_000 + "\n",
        result_file_path=tmp_path / "output.txt",
        result_write_marker=MARKER,
    )

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    reference = reference_in(SERVER_ERROR, context.stderr)
    log_line = logged_with(reference, error_logs)
    assert "x" * 500 in log_line
    assert "x" * 501 not in log_line


async def run_wrapped_then_capture(tmp_path, code: str, result_file_path: Path):
    """Run ``code`` through the real wrap step and child interpreter, then capture it."""
    context = make_context(
        make_worker_job(code=code),
        code_path=tmp_path / "code.py",
        result_file_path=result_file_path,
    )
    await WrapCodeStep()(context)
    completed = subprocess.run(
        [sys.executable, str(context.code_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": str(settings.SHARED_DIR)},
        cwd=tmp_path,
        timeout=60,
    )
    context.returncode = completed.returncode
    context.stderr = completed.stderr

    await CaptureResultStep(max_bytes=MAX_BYTES)(context)

    return context


async def test_real_code_exiting_with_the_write_failure_code_keeps_its_stderr(
    tmp_path, error_logs
):
    code = (
        "import sys\n\ndef main():\n"
        "    print('diagnostics', file=sys.stderr)\n"
        f"    sys.exit({RESULT_WRITE_FAILED_EXIT_CODE})"
    )

    context = await run_wrapped_then_capture(tmp_path, code, tmp_path / "output.txt")

    assert context.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert context.stderr == "diagnostics\n"
    assert error_logs == []


async def test_a_real_unwritable_result_file_is_reported_without_its_path(tmp_path, error_logs):
    result_file = tmp_path / "missing-directory" / "output.txt"
    code = "import sys\n\ndef main():\n    print('note', file=sys.stderr)\n    return 1"

    context = await run_wrapped_then_capture(tmp_path, code, result_file)

    assert context.returncode == 1
    user_output, public_text = context.stderr.split("\n")
    assert user_output == "note"
    assert "missing-directory" not in context.stderr
    reference = reference_in(SERVER_ERROR, public_text)
    assert "missing-directory" in logged_with(reference, error_logs)


async def test_a_result_over_the_cap_fails_without_naming_the_cap(tmp_path):
    result_file = tmp_path / "output.txt"
    result_file.write_bytes(b"x" * 5)
    context = make_context(returncode=0, result_file_path=result_file)

    await CaptureResultStep(max_bytes=4)(context)

    assert context.result_data is None
    assert context.completed is True
    assert context.returncode == 1
    assert context.stderr == "The function's return value is too big to save. Return less data."


async def test_a_result_exactly_at_the_cap_is_read(tmp_path):
    result_file = tmp_path / "output.txt"
    result_file.write_bytes(b"x" * 4)
    context = make_context(returncode=0, result_file_path=result_file)

    await CaptureResultStep(max_bytes=4)(context)

    assert context.result_data == "xxxx"
    assert context.returncode == 0


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


async def test_a_mutations_file_replaced_by_a_symlink_fails_the_run_without_reading_it(
    tmp_path, error_logs
):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"path": "other-org/a.txt", "action": "delete"}]))
    context = storage_context(tmp_path, mutations=None)
    context.storage_mutations_path.symlink_to(outside)

    await CaptureMutationsStep(max_bytes=MAX_BYTES)(context)

    assert context.storage_mutations is None
    assert context.completed is True
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    log_line = logged_with(reference, error_logs)
    assert "symbolic link" in log_line
    assert str(outside) not in log_line


async def test_a_mutations_file_over_the_configured_cap_fails_the_run(tmp_path, error_logs):
    context = storage_context(tmp_path, mutations=[{"path": "docs/a.txt", "action": "put"}])

    await CaptureMutationsStep(max_bytes=4)(context)

    assert context.storage_mutations is None
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    assert "larger than 4 bytes" in logged_with(reference, error_logs)
