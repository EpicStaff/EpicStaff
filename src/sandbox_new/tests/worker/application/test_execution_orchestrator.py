"""Behavior of the execution orchestrator.

It owns what the pipeline steps must not: the per-execution directory is removed
whatever the run did, secrets are scrubbed on the way out, and a result is always sent.
"""

import pytest
from foundation.schemas import ErrorDetailSchema

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.application.steps import ConfigureStorageStep
from worker.domain.models import StorageCredentials, StorageMutations
from tests.builders import make_worker_job


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


async def test_masking_can_be_turned_off(result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, stdout="token is s3cret"),
        result_sink,
        mask_secrets=False,
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    assert result_sink.sent[0][0].stdout == "token is s3cret"


@pytest.mark.parametrize("mask_secrets", [True, False], ids=["masking-on", "masking-off"])
async def test_always_masked_values_are_scrubbed_whatever_the_masking_flag(
    result_sink, mask_secrets
):
    async def step(context):
        context.mask_always("issued-secret")
        context.returncode = 0
        context.stdout = "key is issued-secret"
        context.stderr = "failed with issued-secret"
        context.result_data = '"issued-secret"'
        context.complete()

    orchestrator = build(Pipeline().register(step), result_sink, mask_secrets=mask_secrets)

    await orchestrator.execute(make_worker_job())

    result, _ = result_sink.sent[0]
    assert result.stdout == "key is [REDACTED]"
    assert result.stderr == "failed with [REDACTED]"
    assert result.result == '"[REDACTED]"'


async def test_masking_off_still_leaves_user_secrets_visible_next_to_always_masked_ones(
    result_sink,
):
    async def step(context):
        context.mask_always("issued-secret")
        context.returncode = 0
        context.stdout = "token=s3cret key=issued-secret"
        context.complete()

    orchestrator = build(Pipeline().register(step), result_sink, mask_secrets=False)

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    assert result_sink.sent[0][0].stdout == "token=s3cret key=[REDACTED]"


@pytest.mark.parametrize("mask_secrets", [True, False], ids=["masking-on", "masking-off"])
async def test_storage_credentials_a_run_prints_never_reach_the_result(
    tmp_path, result_sink, mask_secrets
):
    exec_dir = tmp_path / "exec-1"
    exec_dir.mkdir()

    async def prepare_exec_dir(context):
        context.exec_dir = exec_dir

    async def child_that_echoes_its_storage_env(context):
        context.returncode = 0
        context.stdout = f"secret={context.env['STORAGE_SECRET_KEY']}"
        context.stderr = f"access={context.env['STORAGE_ACCESS_KEY']}"
        context.result_data = f'"{context.env["STORAGE_SECRET_KEY"]}"'
        context.complete()

    pipeline = (
        Pipeline()
        .register(prepare_exec_dir)
        .register(
            ConfigureStorageStep(storage_endpoint="http://storage:9000", storage_bucket="sandbox")
        )
        .register(child_that_echoes_its_storage_env)
    )
    orchestrator = build(pipeline, result_sink, mask_secrets=mask_secrets)

    await orchestrator.execute(
        make_worker_job(
            use_storage=True,
            storage_org_prefix="org1",
            storage_credentials=StorageCredentials(
                access_key="ISSUEDACCESSKEY", secret_key="issuedsecretkey123"
            ),
        )
    )

    result, _ = result_sink.sent[0]
    assert result.stdout == "secret=[REDACTED]"
    assert result.stderr == "access=[REDACTED]"
    assert result.result == '"[REDACTED]"'


async def test_a_user_secret_named_like_a_storage_variable_is_still_masked(
    tmp_path, result_sink
):
    # A user keeping their own S3 credentials may well name a secret STORAGE_SECRET_KEY.
    # The worker-issued value must be masked alongside it, not in its place.
    exec_dir = tmp_path / "exec-1"
    exec_dir.mkdir()

    async def prepare_exec_dir(context):
        context.exec_dir = exec_dir

    async def child_that_prints_both_values(context):
        context.returncode = 0
        context.stdout = f"user=user-value issued={context.env['STORAGE_SECRET_KEY']}"
        context.complete()

    pipeline = (
        Pipeline()
        .register(prepare_exec_dir)
        .register(
            ConfigureStorageStep(storage_endpoint="http://storage:9000", storage_bucket="sandbox")
        )
        .register(child_that_prints_both_values)
    )
    orchestrator = build(pipeline, result_sink)

    await orchestrator.execute(
        make_worker_job(
            secrets={"STORAGE_SECRET_KEY": "user-value"},
            use_storage=True,
            storage_org_prefix="org1",
            storage_credentials=StorageCredentials(
                access_key="ISSUEDACCESSKEY", secret_key="issuedsecretkey123"
            ),
        )
    )

    assert result_sink.sent[0][0].stdout == "user=[REDACTED] issued=[REDACTED]"


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


async def test_a_failing_pipeline_step_still_produces_a_result(result_sink):
    async def step(context):
        raise RuntimeError("resolve venv blew up")

    orchestrator = build(Pipeline().register(step), result_sink)

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, _ = result_sink.sent[0]
    assert result.returncode == 1
    assert result.error == ErrorDetailSchema(
        code="server_error", detail="The code couldn't run because of a server error."
    )
    assert result.stderr == ""


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

    await orchestrator.fail(
        "exec-1", "Sandbox failed to run the job.", session_id=7, reply_to_crew_channel=True
    )

    [(result, mutations)] = result_sink.sent
    assert ran == []
    assert result.execution_id == "exec-1"
    assert result.error == ErrorDetailSchema(
        code="server_error", detail="Sandbox failed to run the job."
    )
    assert result.stderr == ""
    assert result.returncode == 1
    assert result.ran is False
    assert result.reply_to_crew_channel is True
    assert result.session_id == 7
    assert result.not_run_reason is None
    assert mutations is None


@pytest.mark.parametrize(
    ("not_run_reason", "expected_code"),
    [("overloaded", "overloaded"), (None, "server_error")],
)
async def test_a_failed_job_carries_its_message_as_a_coded_error(
    result_sink, not_run_reason, expected_code
):
    orchestrator = build(Pipeline(), result_sink)

    await orchestrator.fail(
        "exec-1",
        "Sandbox failed to run the job.",
        session_id=7,
        reply_to_crew_channel=False,
        not_run_reason=not_run_reason,
    )

    [(result, _)] = result_sink.sent
    assert result.error == ErrorDetailSchema(
        code=expected_code, detail="Sandbox failed to run the job."
    )
    assert result.stderr == ""


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
