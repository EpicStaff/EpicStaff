"""Behavior of the manager's two outbound queue adapters.

The dispatcher's job is the domain-to-wire mapping. The one thing that must not slip is
that the worker is handed ``venv_hash`` and never ``venv_id`` -- the worker knows nothing
about the database.
"""

import asyncio

from common.contracts import (
    ExecutionJobMessage,
    ExecutionResultMessage,
    StorageCredentialsMessage,
)
from manager.domain.models import StorageCredentials
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
        storage_credentials=StorageCredentials(access_key="AK123", secret_key="SK456"),
        session_id=11,
        timeout=12.5,
        queue_deadline=1120.0,
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
        storage_credentials=StorageCredentialsMessage(
            access_key="AK123", secret_key="SK456"
        ),
        session_id=11,
        timeout=12.5,
        queue_deadline=1120.0,
    )


async def test_a_job_without_storage_credentials_puts_none_on_the_wire():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()

    await QueueJobDispatcher(queue).dispatch(make_manager_job(storage_credentials=None))

    assert queue.get_nowait().storage_credentials is None


async def test_dispatch_does_not_put_the_venv_id_on_the_wire():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()

    await QueueJobDispatcher(queue).dispatch(make_manager_job(venv_id=4, venv_hash="4abc"))

    assert "venv_id" not in queue.get_nowait().model_dump()


async def test_the_failure_sink_produces_a_failed_result_message():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueJobFailureSink(queue).fail(
        "exec-9",
        "the venv failed to build",
        session_id=11,
        not_run_reason="venv_failed",
        reply_to_crew_channel=False,
    )

    message = queue.get_nowait()
    assert message.execution_id == "exec-9"
    assert message.stderr == "the venv failed to build"
    assert message.returncode == 1
    assert message.result is None
    assert message.ran is False
    assert message.session_id == 11
    assert message.not_run_reason == "venv_failed"


async def test_exec_queued_reports_the_queue_depth_the_job_joined_at(checkpoints):
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    dispatcher = QueueJobDispatcher(queue)

    await dispatcher.dispatch(make_manager_job(execution_id="exec-1", session_id=3))
    await dispatcher.dispatch(make_manager_job(execution_id="exec-2", session_id=4))

    assert checkpoints == [
        {"checkpoint": "exec_queued", "session_id": 3, "execution_id": "exec-1", "queued": 1},
        {"checkpoint": "exec_queued", "session_id": 4, "execution_id": "exec-2", "queued": 2},
    ]


async def test_dispatch_carries_the_crew_reply_flag_to_the_worker():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()

    await QueueJobDispatcher(queue).dispatch(make_manager_job(reply_to_crew_channel=True))

    assert queue.get_nowait().reply_to_crew_channel is True


async def test_a_job_that_never_ran_keeps_the_crew_reply_flag_on_its_failed_result():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueJobFailureSink(queue).fail(
        "exec-9",
        "the venv failed to build",
        session_id=11,
        not_run_reason="venv_failed",
        reply_to_crew_channel=True,
    )

    assert queue.get_nowait().reply_to_crew_channel is True
