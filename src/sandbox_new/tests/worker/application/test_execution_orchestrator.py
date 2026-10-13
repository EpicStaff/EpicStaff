"""Behavior of the execution orchestrator.

It owns what the pipeline steps must not: scoped credentials are revoked and the
per-execution directory is removed whatever the run did, secrets are scrubbed on the way
out, and a result is always sent.
"""

from worker.application.orchestrator import ExecutionOrchestrator
from worker.application.pipeline import Pipeline
from worker.domain.models import StorageCredentials, StorageMutations
from tests.builders import make_worker_job
from tests.fakes import FAKE_ACCESS_KEY


def pipeline_that(**fields):
    """A one-step pipeline that writes the given fields onto the context and completes."""

    async def step(context):
        for name, value in fields.items():
            setattr(context, name, value)
        context.complete()

    return Pipeline().register(step)


def build(pipeline, storage_credentials, result_sink, *, mask_secrets: bool = True):
    return ExecutionOrchestrator(
        pipeline,
        credentials=storage_credentials,
        result_sink=result_sink,
        mask_secrets=mask_secrets,
    )


async def test_a_successful_run_sends_the_context_outcome(storage_credentials, result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, stdout="out", stderr="", result_data="42"),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, mutations = result_sink.sent[0]
    assert result.execution_id == "exec-1"
    assert result.result == "42"
    assert result.stdout == "out"
    assert result.returncode == 0
    assert mutations is None


async def test_secrets_are_scrubbed_from_every_output_field(storage_credentials, result_sink):
    orchestrator = build(
        pipeline_that(
            returncode=0,
            stdout="token is s3cret",
            stderr="failed with s3cret",
            result_data='{"echo": "s3cret"}',
        ),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    result, _ = result_sink.sent[0]
    assert result.stdout == "token is [REDACTED]"
    assert result.stderr == "failed with [REDACTED]"
    assert result.result == '{"echo": "[REDACTED]"}'


async def test_masking_can_be_turned_off(storage_credentials, result_sink):
    orchestrator = build(
        pipeline_that(returncode=0, stdout="token is s3cret"),
        storage_credentials,
        result_sink,
        mask_secrets=False,
    )

    await orchestrator.execute(make_worker_job(secrets={"TOKEN": "s3cret"}))

    assert result_sink.sent[0][0].stdout == "token is s3cret"


async def test_provisioned_credentials_are_revoked_after_the_run(
    storage_credentials, result_sink
):
    orchestrator = build(
        pipeline_that(
            returncode=0,
            storage_credentials=StorageCredentials(
                access_key=FAKE_ACCESS_KEY, secret_key="whatever"
            ),
        ),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job())

    assert storage_credentials.revoked == [FAKE_ACCESS_KEY]


async def test_nothing_is_revoked_when_nothing_was_provisioned(
    storage_credentials, result_sink
):
    orchestrator = build(pipeline_that(returncode=0), storage_credentials, result_sink)

    await orchestrator.execute(make_worker_job())

    assert storage_credentials.revoked == []


async def test_a_failing_revoke_still_lets_the_result_out(storage_credentials, result_sink):
    storage_credentials.fail_revoke = RuntimeError("minio is down")
    orchestrator = build(
        pipeline_that(
            returncode=0,
            storage_credentials=StorageCredentials(access_key=FAKE_ACCESS_KEY, secret_key="x"),
        ),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job())

    assert len(result_sink.sent) == 1


async def test_the_execution_directory_is_removed_after_the_run(
    tmp_path, storage_credentials, result_sink
):
    exec_dir = tmp_path / "exec-1"
    exec_dir.mkdir()
    (exec_dir / "code.py").write_text("print(1)")
    orchestrator = build(
        pipeline_that(returncode=0, exec_dir=exec_dir), storage_credentials, result_sink
    )

    await orchestrator.execute(make_worker_job())

    assert not exec_dir.exists()
    assert len(result_sink.sent) == 1


async def test_a_failing_cleanup_still_lets_the_result_out(
    tmp_path, storage_credentials, result_sink
):
    orchestrator = build(
        pipeline_that(returncode=0, exec_dir=tmp_path / "never-created"),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job())

    assert len(result_sink.sent) == 1


async def test_a_run_without_a_return_code_is_reported_as_a_failure(
    storage_credentials, result_sink
):
    async def step(context):
        context.complete()

    orchestrator = build(Pipeline().register(step), storage_credentials, result_sink)

    await orchestrator.execute(make_worker_job())

    assert result_sink.sent[0][0].returncode == 1


async def test_storage_mutations_are_handed_to_the_sink(storage_credentials, result_sink):
    mutations = StorageMutations(
        execution_id="exec-1", org_prefix="org1", session_id=7, mutations=[{"path": "a.txt"}]
    )
    orchestrator = build(
        pipeline_that(returncode=0, storage_mutations=mutations),
        storage_credentials,
        result_sink,
    )

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    assert result_sink.sent[0][1] == mutations


async def test_a_failing_pipeline_step_still_produces_a_result(
    storage_credentials, result_sink
):
    async def step(context):
        raise RuntimeError("resolve venv blew up")

    orchestrator = build(Pipeline().register(step), storage_credentials, result_sink)

    await orchestrator.execute(make_worker_job(execution_id="exec-1"))

    result, _ = result_sink.sent[0]
    assert result.returncode == 1
    assert "resolve venv blew up" in result.stderr
