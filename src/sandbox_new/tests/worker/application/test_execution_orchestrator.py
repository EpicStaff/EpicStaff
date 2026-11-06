"""Behavior of the execution orchestrator.

It owns what the pipeline steps must not: the per-execution directory is removed
whatever the run did, secrets are scrubbed on the way out, and a result is always sent.
"""

import pytest
from src.shared.models.code_failure import CodeFailure, CodeFailureCode, UserCodeError

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.domain.models import StorageMutations
from tests.builders import make_worker_job
from tests.public_errors import SERVER_ERROR, logged_with, reference_in


def pipeline_that(**fields):
    """A one-step pipeline that writes the given fields onto the context and completes."""

    async def step(context):
        for name, value in fields.items():
            setattr(context, name, value)
        context.complete()

    return Pipeline().register(step)


def build(pipeline, result_sink, *, mask_secrets: bool = True):
    return ExecutionOrchestrator(
        pipeline,
        result_sink=result_sink,
        mask_secrets=mask_secrets,
    )


async def test_a_successful_run_sends_the_context_outcome(result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, stdout="out", stderr="", result_data="42"),
        result_sink,
    )

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, mutations = result_sink.sent[0]
    assert result.execution_id == "exec-1"
    assert result.result == "42"
    assert result.stdout == "out"
    assert result.returncode == 0
    assert mutations is None


async def test_secrets_are_scrubbed_from_every_output_field(result_sink):
    orchestrator = build(
        pipeline_that(
            returncode=0,
            stdout="token is s3cret",
            stderr="failed with s3cret",
            result_data='{"echo": "s3cret"}',
        ),
        result_sink,
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    result, _ = result_sink.sent[0]
    assert result.stdout == "token is [REDACTED]"
    assert result.stderr == "failed with [REDACTED]"
    assert result.result == '{"echo": "[REDACTED]"}'


@pytest.mark.parametrize(
    "failure",
    [
        CodeFailure(
            code=CodeFailureCode.USER_CODE_ERROR,
            detail="ValueError on line 2: bad token s3cret",
            user_error=UserCodeError(
                exception_type="ValueError", line=2, message="bad token s3cret"
            ),
        ),
        CodeFailure(
            code=CodeFailureCode.UNEXPECTED_ARGUMENT,
            detail="TypeError: main() got an unexpected keyword argument 's3cret'",
            attr="s3cret",
        ),
    ],
    ids=["user-code-error", "argument"],
)
async def test_secrets_are_scrubbed_from_every_part_of_the_failure(result_sink, failure):
    orchestrator = build(
        pipeline_that(returncode=1, stderr=failure.detail, failure=failure), result_sink
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    sent = result_sink.sent[0][0].failure
    assert "s3cret" not in sent.model_dump_json()
    assert sent.detail == failure.detail.replace("s3cret", "[REDACTED]")
    assert sent.code == failure.code
    if failure.user_error is not None:
        assert sent.user_error.message == "bad token [REDACTED]"
        assert (sent.user_error.exception_type, sent.user_error.line) == ("ValueError", 2)
    if failure.attr is not None:
        assert sent.attr == "[REDACTED]"


SECRET = "sk-live-0123456789abcdef"


async def test_a_secret_straddling_the_shortened_length_leaves_no_prefix(result_sink):
    # The secret starts 10 characters before the 4000-character cut.
    message = "x" * 3990 + SECRET + "y" * 100
    failure = CodeFailure(
        code=CodeFailureCode.USER_CODE_ERROR,
        detail=f"ValueError: {message}",
        user_error=UserCodeError(exception_type="ValueError", line=None, message=message),
    )
    orchestrator = build(
        pipeline_that(returncode=1, stderr=failure.detail, failure=failure), result_sink
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": SECRET}))

    result = result_sink.sent[0][0]
    sent = result.failure
    assert SECRET[:4] not in sent.detail
    assert SECRET[:4] not in sent.user_error.message
    assert sent.user_error.message == "x" * 3990 + "[REDACTED]"[:10] + "..."
    assert len(sent.detail) == 4000 + len("...")
    # Stderr is the run's whole output: masked, never shortened.
    assert result.stderr == f"ValueError: {'x' * 3990}[REDACTED]{'y' * 100}"


async def test_a_secret_in_the_exception_type_is_masked(result_sink):
    failure = CodeFailure(
        code=CodeFailureCode.USER_CODE_ERROR,
        detail=f"{SECRET} on line 2",
        user_error=UserCodeError(exception_type=SECRET, line=2, message=""),
    )
    orchestrator = build(
        pipeline_that(returncode=1, stderr=failure.detail, failure=failure), result_sink
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": SECRET}))

    assert result_sink.sent[0][0].failure.user_error.exception_type == "[REDACTED]"


@pytest.mark.parametrize("mask_secrets", [True, False], ids=["masked", "unmasked"])
async def test_the_texts_a_user_is_shown_are_shortened(result_sink, mask_secrets):
    failure = CodeFailure(
        code=CodeFailureCode.USER_CODE_ERROR,
        detail="d" * 5000,
        user_error=UserCodeError(exception_type="T" * 300, line=None, message="m" * 5000),
    )
    orchestrator = build(
        pipeline_that(returncode=1, stderr=failure.detail, failure=failure),
        result_sink,
        mask_secrets=mask_secrets,
    )

    await orchestrator.execute(make_worker_job())

    result = result_sink.sent[0][0]
    assert result.failure.detail == "d" * 4000 + "..."
    assert result.failure.user_error.message == "m" * 4000 + "..."
    assert result.failure.user_error.exception_type == "T" * 200 + "..."
    assert result.stderr == "d" * 5000


async def test_an_argument_name_is_shortened(result_sink):
    failure = CodeFailure(
        code=CodeFailureCode.UNEXPECTED_ARGUMENT, detail="TypeError: unexpected", attr="a" * 300
    )
    orchestrator = build(pipeline_that(returncode=1, failure=failure), result_sink)

    await orchestrator.execute(make_worker_job())

    assert result_sink.sent[0][0].failure.attr == "a" * 200 + "..."


async def test_the_failure_and_its_reference_reach_the_result(result_sink):
    failure = CodeFailure(code=CodeFailureCode.EXECUTION_TIMEOUT, detail="ran too long")
    orchestrator = build(
        pipeline_that(returncode=124, failure=failure, reference="0a1b2c3d4e5f"), result_sink
    )

    await orchestrator.execute(make_worker_job())

    result = result_sink.sent[0][0]
    assert (result.failure, result.reference) == (failure, "0a1b2c3d4e5f")


async def test_masking_can_be_turned_off(result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, stdout="token is s3cret"),
        result_sink,
        mask_secrets=False,
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    assert result_sink.sent[0][0].stdout == "token is s3cret"


async def test_the_execution_directory_is_removed_after_the_run(tmp_path, result_sink):
    exec_dir = tmp_path / "exec-1"
    exec_dir.mkdir()
    (exec_dir / "code.py").write_text("print(1)")
    orchestrator = build(pipeline_that(returncode=0, exec_dir=exec_dir), result_sink)

    await orchestrator.execute(make_worker_job())

    assert not exec_dir.exists()
    assert len(result_sink.sent) == 1


async def test_a_failing_cleanup_still_lets_the_result_out(tmp_path, result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, exec_dir=tmp_path / "never-created"),
        result_sink,
    )

    await orchestrator.execute(make_worker_job())

    assert len(result_sink.sent) == 1


async def test_a_run_without_a_return_code_is_reported_as_a_failure(result_sink):
    async def step(context):
        context.complete()

    orchestrator = build(Pipeline().register(step), result_sink)

    await orchestrator.execute(make_worker_job())

    assert result_sink.sent[0][0].returncode == 1


async def test_storage_mutations_are_handed_to_the_sink(result_sink):
    mutations = StorageMutations(
        execution_id="exec-1", org_prefix="org1", session_id=7, mutations=[{"path": "a.txt"}]
    )
    orchestrator = build(
        pipeline_that(returncode=0, storage_mutations=mutations),
        result_sink,
    )

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    assert result_sink.sent[0][1] == mutations


async def test_a_failing_pipeline_step_still_produces_a_result(result_sink, error_logs):
    async def step(context):
        raise RuntimeError("resolve venv blew up")

    orchestrator = build(Pipeline().register(step), result_sink)

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, _ = result_sink.sent[0]
    assert result.returncode == 1
    reference = reference_in(SERVER_ERROR, result.stderr)
    assert (result.failure.code, result.failure.detail) == ("sandbox_error", result.stderr)
    assert result.reference == reference
    assert "resolve venv blew up" in logged_with(reference, error_logs)


async def test_secrets_are_scrubbed_from_the_child_output_before_a_sandbox_failure(result_sink):
    async def step(context):
        context.stderr = "printed s3cret"
        raise RuntimeError("capture blew up")

    orchestrator = build(Pipeline().register(step), result_sink)

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    result, _ = result_sink.sent[0]
    child_output, public_text = result.stderr.split("\n")
    assert child_output == "printed [REDACTED]"
    reference_in(SERVER_ERROR, public_text)


async def test_a_run_is_marked_as_having_run(result_sink):
    orchestrator = build(pipeline_that(returncode=1, stderr="boom"), result_sink)

    await orchestrator.execute(make_worker_job())

    assert result_sink.sent[0][0].ran is True


async def test_failing_a_job_sends_a_failed_result_without_running_it(result_sink):
    ran = []

    async def step(context):
        ran.append(context.job.execution_id)
        context.complete()

    orchestrator = build(Pipeline().register(step), result_sink)

    failure = CodeFailure(code=CodeFailureCode.SANDBOX_ERROR, detail="Sandbox failed to run it.")

    await orchestrator.fail(
        "exec-1", failure, reference="0a1b2c3d4e5f", session_id=7, reply_to_crew_channel=True
    )

    [(result, mutations)] = result_sink.sent
    assert ran == []
    assert result.execution_id == "exec-1"
    assert result.stderr == "Sandbox failed to run it."
    assert result.returncode == 1
    assert (result.failure, result.reference) == (failure, "0a1b2c3d4e5f")
    assert result.ran is False
    assert result.reply_to_crew_channel is True
    assert result.session_id == 7
    assert mutations is None


async def failing_step(context):
    raise RuntimeError("resolve venv blew up")


@pytest.mark.parametrize(
    ("pipeline", "returncode"),
    [
        (pipeline_that(returncode=0), 0),
        (pipeline_that(returncode=3, stderr="Traceback"), 3),
        (Pipeline().register(failing_step), 1),
    ],
    ids=["success", "code-failed", "step-raised"],
)
async def test_every_run_logs_exec_end_with_the_return_code_it_sends(
    checkpoints, result_sink, pipeline, returncode
):
    orchestrator = build(pipeline, result_sink)

    await orchestrator.execute(make_worker_job(execution_id="exec-9", session_id=4))

    assert checkpoints == [
        {
            "checkpoint": "exec_end",
            "session_id": 4,
            "execution_id": "exec-9",
            "returncode": returncode,
        },
    ]
    assert result_sink.sent[0][0].returncode == returncode


async def test_the_result_carries_the_jobs_session_id(result_sink):
    orchestrator = build(pipeline_that(returncode=0), result_sink)

    await orchestrator.execute(make_worker_job(session_id=4))

    assert result_sink.sent[0][0].session_id == 4
