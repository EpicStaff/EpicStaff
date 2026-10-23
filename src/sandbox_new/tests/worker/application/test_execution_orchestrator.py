"""Behavior of the execution orchestrator.

It owns what the pipeline steps must not: the per-execution directory is removed
whatever the run did, secrets are scrubbed on the way out, and a result is always sent.
"""

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.domain.models import StorageMutations
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
    assert "resolve venv blew up" in result.stderr


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

    await orchestrator.fail("exec-1", "Sandbox failed to run the job.", reply_to_crew_channel=True)

    [(result, mutations)] = result_sink.sent
    assert ran == []
    assert result.execution_id == "exec-1"
    assert result.stderr == "Sandbox failed to run the job."
    assert result.returncode == 1
    assert result.ran is False
    assert result.reply_to_crew_channel is True
    assert mutations is None
