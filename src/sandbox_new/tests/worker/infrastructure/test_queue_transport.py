"""Behavior of the worker's two queue adapters.

They own the wire shape so the application never sees it: the job source decodes an
``ExecutionJobMessage`` into a domain ``Job``, the result sink encodes the domain result
back into an ``ExecutionResultMessage``.
"""

import asyncio

import pytest

from common.contracts import (
    ExecutionJobMessage,
    ExecutionResultMessage,
    StorageCredentialsMessage,
)
from worker.application.ports import UndecodableJobError
from worker.domain.models import ExecutionResult, StorageMutations
from worker.infrastructure.transport.queue_job_source import QueueJobSource
from worker.infrastructure.transport.queue_result_sink import QueueResultSink


async def test_a_wire_job_decodes_into_a_domain_job():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    queue.put_nowait(
        ExecutionJobMessage(
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
    )

    job = await QueueJobSource(queue).get()

    assert job.execution_id == "exec-9"
    assert job.venv_hash == "4abc"
    assert job.code == "def main():\n    return 2"
    assert job.entrypoint == "main"
    assert job.func_kwargs == {"value": 1}
    assert job.global_kwargs == {"LIMIT": 3}
    assert job.secrets == {"TOKEN": "s3cret"}
    assert job.use_storage is True
    assert job.storage_allowed_paths == ["docs/"]
    assert job.storage_org_prefix == "org1"
    assert job.storage_credentials.access_key == "AK123"
    assert job.storage_credentials.secret_key == "SK456"
    assert job.session_id == 11
    assert job.timeout == 12.5
    assert job.queue_deadline == 1120.0


async def test_a_minimal_wire_job_decodes_with_its_defaults():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    queue.put_nowait(
        ExecutionJobMessage(execution_id="exec-1", venv_hash="1abc", code="", entrypoint="main")
    )

    job = await QueueJobSource(queue).get()

    assert job.use_storage is False
    assert job.secrets == {}
    assert job.storage_credentials is None
    assert job.timeout is None
    assert job.session_id is None
    assert job.reply_to_crew_channel is False


async def test_a_result_without_mutations_encodes_onto_the_wire():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueResultSink(queue).send(
        ExecutionResult(
            execution_id="exec-1",
            result="42",
            stdout="out",
            stderr="err",
            returncode=0,
            session_id=7,
        )
    )

    message = queue.get_nowait()
    assert message.execution_id == "exec-1"
    assert message.result == "42"
    assert message.stdout == "out"
    assert message.stderr == "err"
    assert message.returncode == 0
    assert message.session_id == 7
    assert message.mutations is None
    assert message.not_run_reason is None


async def test_mutations_are_carried_onto_the_wire():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueResultSink(queue).send(
        ExecutionResult(execution_id="exec-1", returncode=0),
        mutations=StorageMutations(
            execution_id="exec-1",
            org_prefix="org1",
            session_id=7,
            mutations=[{"path": "docs/a.txt"}],
        ),
    )

    message = queue.get_nowait()
    assert message.mutations.org_prefix == "org1"
    assert message.mutations.session_id == 7
    assert message.mutations.mutations == [{"path": "docs/a.txt"}]


async def test_the_crew_reply_flag_decodes_onto_the_worker_job():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    queue.put_nowait(
        ExecutionJobMessage(
            execution_id="exec-1",
            venv_hash="1abc",
            code="",
            entrypoint="main",
            reply_to_crew_channel=True,
        )
    )

    job = await QueueJobSource(queue).get()

    assert job.reply_to_crew_channel is True


async def test_the_crew_reply_flag_is_encoded_back_onto_the_wire_result():
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueResultSink(queue).send(
        ExecutionResult(execution_id="exec-1", reply_to_crew_channel=True)
    )

    assert queue.get_nowait().reply_to_crew_channel is True


async def test_a_wire_job_that_does_not_decode_raises_with_what_is_needed_to_fail_it():
    queue: asyncio.Queue[ExecutionJobMessage] = asyncio.Queue()
    # Built without validation: the manager never sends a job without a venv hash, so
    # this is the drifted contract the source must still answer for.
    queue.put_nowait(
        ExecutionJobMessage.model_construct(
            execution_id="exec-1",
            venv_hash=None,
            code="",
            entrypoint="main",
            secrets={"TOKEN": "s3cret"},
            reply_to_crew_channel=True,
        )
    )

    with pytest.raises(UndecodableJobError) as raised:
        await QueueJobSource(queue).get()

    assert raised.value.execution_id == "exec-1"
    assert raised.value.reply_to_crew_channel is True
    assert "s3cret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("ran", [True, False])
async def test_whether_the_job_ran_is_encoded_onto_the_wire_result(ran):
    queue: asyncio.Queue[ExecutionResultMessage] = asyncio.Queue()

    await QueueResultSink(queue).send(ExecutionResult(execution_id="exec-1", ran=ran))

    assert queue.get_nowait().ran is ran
