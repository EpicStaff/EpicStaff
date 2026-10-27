"""Behavior of the execution pipeline and the context it threads through.

The contract that matters: the pipeline never raises. A failing step becomes a failed
outcome on the context, so the worker returns an error instead of going down.
"""

from worker.application.context import ExecutionContext
from worker.application.pipeline import Pipeline
from tests.builders import make_context, make_worker_job


def record(name: str, seen: list[str]):
    async def step(context: ExecutionContext) -> None:
        seen.append(name)

    return step


async def complete_step(context: ExecutionContext) -> None:
    context.returncode = 0
    context.complete()


async def raising_step(context: ExecutionContext) -> None:
    raise RuntimeError("step blew up")


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


async def test_a_raising_step_becomes_a_failed_outcome():
    seen: list[str] = []
    pipeline = Pipeline().register(raising_step).register(record("after", seen))

    context = await pipeline.run(make_context())

    assert seen == []
    assert context.completed is True
    assert context.returncode == 1
    assert context.stderr == "step blew up"


async def test_a_pipeline_that_produces_no_result_fails_the_run():
    seen: list[str] = []
    context = await Pipeline().register(record("a", seen)).run(make_context())

    assert seen == ["a"]
    assert context.completed is True
    assert context.returncode == 1
    assert "produced no result" in context.stderr


async def test_an_empty_pipeline_fails_the_run():
    context = await Pipeline().run(make_context())

    assert context.returncode == 1
    assert "produced no result" in context.stderr


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
