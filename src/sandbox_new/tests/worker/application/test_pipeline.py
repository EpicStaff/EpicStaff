"""Behavior of the execution pipeline and the context it threads through.

The contract that matters: the pipeline never raises. A failing step becomes a failed
outcome on the context, so the worker returns an error instead of going down. That
failure is the sandbox's own, so the user sees a generic server error and the raw
detail is only logged, under the reference the user's text cites.
"""

from common.public_errors import SandboxFailureMessage

from worker.application.context import ExecutionContext, fail_on_sandbox_error
from worker.application.pipeline import Pipeline
from tests.builders import make_context, make_worker_job
from tests.public_errors import SERVER_ERROR, UNSAFE_TO_RUN, logged_with, reference_in


def record(name: str, seen: list[str]):
    async def step(context: ExecutionContext) -> None:
        seen.append(name)

    return step


async def complete_step(context: ExecutionContext) -> None:
    context.returncode = 0
    context.complete()


async def raising_step(context: ExecutionContext) -> None:
    raise RuntimeError("step blew up at /srv/internal with SANDBOX_SETTING=1")


async def test_steps_run_in_registration_order():
    seen: list[str] = []
    pipeline = Pipeline().register(record("a", seen)).register(record("b", seen))
    pipeline.register(complete_step)

    await pipeline.run(make_context())

    assert seen == ["a", "b"]


async def test_a_completed_context_stops_the_remaining_steps():
    seen: list[str] = []
    pipeline = Pipeline().register(complete_step).register(record("after", seen))

    context = await pipeline.run(make_context())

    assert seen == []
    assert context.returncode == 0


async def test_a_raising_step_becomes_a_failed_outcome_showing_only_a_reference(error_logs):
    seen: list[str] = []
    pipeline = Pipeline().register(raising_step).register(record("after", seen))

    context = await pipeline.run(make_context(make_worker_job(execution_id="exec-7")))

    assert seen == []
    assert context.completed is True
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    log_line = logged_with(reference, error_logs)
    assert "exec-7" in log_line
    assert "step blew up at /srv/internal with SANDBOX_SETTING=1" in log_line


async def test_a_secret_quoted_by_a_raising_step_is_masked_in_the_log(error_logs):
    async def step_quoting_a_secret(context: ExecutionContext) -> None:
        raise RuntimeError("request with token s3cret-value was refused")

    context = make_context(make_worker_job(secrets={"API_TOKEN": "s3cret-value"}))

    await Pipeline().register(step_quoting_a_secret).run(context)

    log_line = logged_with(reference_in(SERVER_ERROR, context.stderr), error_logs)
    assert "s3cret-value" not in log_line
    assert "RuntimeError: request with token [REDACTED] was refused" in log_line
    assert "step_quoting_a_secret" in log_line


def test_a_secret_in_a_text_detail_is_masked_in_the_log(error_logs):
    context = make_context(make_worker_job(secrets={"API_TOKEN": "s3cret-value"}))

    fail_on_sandbox_error(context, "storage rejected key s3cret-value")

    log_line = logged_with(reference_in(SERVER_ERROR, context.stderr), error_logs)
    assert log_line.rstrip("\n").endswith("storage rejected key [REDACTED]")


async def test_a_pipeline_that_produces_no_result_fails_the_run(error_logs):
    seen: list[str] = []
    context = await Pipeline().register(record("a", seen)).run(make_context())

    assert seen == ["a"]
    assert context.completed is True
    assert context.returncode == 1
    reference = reference_in(SERVER_ERROR, context.stderr)
    assert "produced no result" in logged_with(reference, error_logs)


async def test_an_empty_pipeline_fails_the_run():
    context = await Pipeline().run(make_context())

    assert context.returncode == 1
    reference_in(SERVER_ERROR, context.stderr)


def test_every_sandbox_failure_gets_its_own_reference():
    first, second = make_context(), make_context()

    fail_on_sandbox_error(first, "boom")
    fail_on_sandbox_error(second, "boom")

    assert reference_in(SERVER_ERROR, first.stderr) != reference_in(SERVER_ERROR, second.stderr)


def test_a_sandbox_failure_keeps_the_output_the_child_already_wrote():
    context = make_context(stderr="child wrote this")

    fail_on_sandbox_error(context, "boom", public_message=SandboxFailureMessage.UNSAFE_TO_RUN)

    child_output, public_text = context.stderr.split("\n")
    assert child_output == "child wrote this"
    reference_in(UNSAFE_TO_RUN, public_text)


def test_fail_appends_to_an_existing_stderr():
    context = make_context(stderr="child wrote this")

    context.fail("and then the step blew up")

    assert context.stderr == "child wrote this\nand then the step blew up"


def test_fail_on_an_empty_stderr_does_not_add_a_leading_newline():
    context = make_context()

    context.fail("step blew up")

    assert context.stderr == "step blew up"


def test_fail_accepts_a_custom_return_code():
    context = make_context()

    context.fail("timed out", returncode=124)

    assert context.returncode == 124
    assert context.completed is True


def test_complete_does_not_invent_a_return_code():
    context = ExecutionContext(job=make_worker_job())

    context.complete()

    assert context.completed is True
    assert context.returncode is None
