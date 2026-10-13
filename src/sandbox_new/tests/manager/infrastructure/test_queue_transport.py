"""Behavior of the manager's two outbound queue adapters.

The dispatcher's job is the domain-to-wire mapping. The one thing that must not slip is
that the worker is handed ``venv_hash`` and never ``venv_id`` -- the worker knows nothing
about the database.
"""

import asyncio

from common.contracts import ExecutionJobMessage, ExecutionResultMessage
from manager.infrastructure.transport.queue_job_dispatcher import QueueJobDispatcher
from manager.infrastructure.transport.queue_job_failure_sink import QueueJobFailureSink
from tests.builders import make_manager_job


async def test_dispatch_maps_every_field_onto_the_wire_message():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    job = make_manager_job(
        execution_id="exec-9",
        venv_id=4,
        venv_hash="4abc",
        code="def main():\n    return 2",
        entrypoint="main",
        func_kwargs={"value": 1},
        global_kwargs={"LIMIT": 3},
        secrets={"TOKEN": "s3cret"},
        use_storage=True,
        storage_allowed_paths=["docs/"],
        storage_org_prefix="org1",
        session_id=11,
        timeout=12.5,
    )

    await QueueJobDispatcher(queue).dispatch(job)

    message = queue.get_nowait()
    assert message == ExecutionJobMessage(
        execution_id="exec-9",
        venv_hash="4abc",
        code="def main():\n    return 2",
        entrypoint="main",
        func_kwargs={"value": 1},
        global_kwargs={"LIMIT": 3},
        secrets={"TOKEN": "s3cret"},
        use_storage=True,
        storage_allowed_paths=["docs/"],
        storage_org_prefix="org1",
        session_id=11,
        timeout=12.5,
    )


async def test_dispatch_does_not_put_the_venv_id_on_the_wire():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()

    await QueueJobDispatcher(queue).dispatch(make_manager_job(venv_id=4, venv_hash="4abc"))

    assert "venv_id" not in queue.get_nowait().model_dump()


async def test_the_failure_sink_produces_a_failed_result_message():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueJobFailureSink(queue).fail("exec-9", "the venv failed to build")

    message = queue.get_nowait()
    assert message.execution_id == "exec-9"
    assert message.stderr == "the venv failed to build"
    assert message.returncode == 1
    assert message.result is None
