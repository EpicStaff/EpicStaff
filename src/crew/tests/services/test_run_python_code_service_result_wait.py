"""RunPythonCodeService waits for the sandbox's result on crew's own result channel.

One subscription per process parses each result once and hands it to the
execution waiting for it; a wait ends on the result, the timeout, or a stop.
"""

import asyncio
import json

import fakeredis
import pytest
import pytest_asyncio

import settings
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.redis_service import RedisService
from services.run_python_code_service import TIMEOUT_STDERR_MESSAGE, RunPythonCodeService
from src.shared.models import CodeResultData, PythonCodeData
from tests.services.conftest import (
    CODE_EXEC_CHANNEL,
    CREW_RESULT_CHANNEL,
    SHARED_RESULT_CHANNEL,
)
from utils.singleton_meta import SingletonMeta

pytestmark = pytest.mark.asyncio


def make_python_code_data() -> PythonCodeData:
    return PythonCodeData(
        venv_name="default",
        code="def main(**kw): return kw",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
    )


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", 0.05)


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest_asyncio.fixture
async def redis_service_on_fakeredis(fake_server, code_channels):
    SingletonMeta._instances.pop(RedisService, None)
    redis_service = RedisService(
        host="127.0.0.1", port=6379, user="default", password="redis_password"
    )
    redis_service.aioredis_client = fakeredis.FakeAsyncRedis(
        server=fake_server, decode_responses=True
    )
    yield redis_service
    for group in redis_service._async_pubsub_groups.values():
        await group.stop()
    SingletonMeta._instances.pop(RedisService, None)


async def test_returns_the_sandbox_result_through_real_redis_pubsub(
    redis_service_on_fakeredis, fake_server
):
    service = RunPythonCodeService(redis_service=redis_service_on_fakeredis)
    await service.subscribe_to_results()
    sandbox_client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    sandbox_pubsub = sandbox_client.pubsub()
    await sandbox_pubsub.subscribe(CODE_EXEC_CHANNEL)

    async def answer_one_task() -> None:
        async for message in sandbox_pubsub.listen():
            if message["type"] != "message":
                continue
            task = json.loads(message["data"])
            await sandbox_client.publish(
                CREW_RESULT_CHANNEL,
                CodeResultData(
                    execution_id=task["execution_id"], result_data="42", stderr="", stdout=""
                ).model_dump_json(),
            )
            return

    sandbox = asyncio.ensure_future(answer_one_task())
    try:
        result = await asyncio.wait_for(
            service.run_code(python_code_data=make_python_code_data(), inputs={}), timeout=5
        )
    finally:
        sandbox.cancel()
        await sandbox_pubsub.aclose()
        await sandbox_client.aclose()

    assert result["result_data"] == "42"
    assert result["returncode"] == 0


async def test_returns_the_result_the_sandbox_publishes_for_the_execution(
    run_python_code_service, sandbox
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.reply(task["execution_id"], result_data="ok")

    result = await asyncio.wait_for(run, timeout=5)

    assert task["reply_to_crew_channel"] is True
    assert result["execution_id"] == task["execution_id"]
    assert result["result_data"] == "ok"
    assert result["returncode"] == 0


async def test_returns_a_result_published_before_the_wait_starts(
    run_python_code_service, sandbox
):
    sandbox.auto_reply = True

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["execution_id"] == sandbox.tasks[0]["execution_id"]
    assert result["result_data"] == "ok"


async def test_returns_timeout_result_when_no_result_arrives(
    run_python_code_service, sandbox, short_timeout
):
    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["execution_id"] == sandbox.tasks[0]["execution_id"]
    assert result["returncode"] == 124
    assert result["stderr"] == TIMEOUT_STDERR_MESSAGE
    assert result["result_data"] is None


async def test_waits_until_the_result_when_timeout_is_none(
    run_python_code_service, sandbox, monkeypatch
):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await asyncio.sleep(0.05)
    await sandbox.reply(task["execution_id"], result_data="late")

    result = await asyncio.wait_for(run, timeout=5)

    assert result["result_data"] == "late"


async def test_stop_event_set_during_the_wait_aborts_it(run_python_code_service, sandbox):
    stop_event = StopEvent()
    run = asyncio.ensure_future(
        run_python_code_service.run_code(
            python_code_data=make_python_code_data(), inputs={}, stop_event=stop_event
        )
    )
    await sandbox.wait_for_tasks(1)
    stop_event.set()

    with pytest.raises(StopSession):
        await asyncio.wait_for(run, timeout=5)


@pytest.mark.parametrize(
    ("channel", "foreign_execution_id"),
    [
        pytest.param(CREW_RESULT_CHANNEL, "another-execution", id="other-execution-on-crew-channel"),
        pytest.param(SHARED_RESULT_CHANNEL, None, id="own-execution-on-shared-channel"),
    ],
)
async def test_ignores_results_not_addressed_to_the_execution(
    run_python_code_service, sandbox, pubsub, short_timeout, channel, foreign_execution_id
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await pubsub.apublish(
        channel,
        CodeResultData(
            execution_id=foreign_execution_id or task["execution_id"],
            result_data="not yours",
            stderr="",
            stdout="",
        ).model_dump_json(),
    )

    result = await asyncio.wait_for(run, timeout=5)

    assert result["returncode"] == 124
    assert result["result_data"] is None


async def test_unparseable_message_is_dropped_and_the_wait_continues(
    run_python_code_service, sandbox, pubsub
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await pubsub.apublish(CREW_RESULT_CHANNEL, "not json")
    await sandbox.reply(task["execution_id"], result_data="ok")

    result = await asyncio.wait_for(run, timeout=5)

    assert result["result_data"] == "ok"


async def test_concurrent_executions_each_get_their_own_result_from_one_subscription(
    run_python_code_service, sandbox, pubsub
):
    runs = [
        asyncio.ensure_future(
            run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
        )
        for _ in range(3)
    ]
    tasks = await sandbox.wait_for_tasks(3)
    for task in reversed(tasks):
        await sandbox.reply(task["execution_id"], result_data=task["execution_id"])

    results = await asyncio.wait_for(asyncio.gather(*runs), timeout=5)

    assert [result["result_data"] for result in results] == [
        result["execution_id"] for result in results
    ]
    assert len({result["execution_id"] for result in results}) == 3
    assert len(pubsub.subscribers[CREW_RESULT_CHANNEL]) == 1


@pytest.mark.parametrize("ending", ["result", "timeout", "stop", "cancelled"])
async def test_wait_leaves_no_pending_execution_behind(
    run_python_code_service, sandbox, short_timeout, ending
):
    stop_event = StopEvent()
    run = asyncio.ensure_future(
        run_python_code_service.run_code(
            python_code_data=make_python_code_data(), inputs={}, stop_event=stop_event
        )
    )
    [task] = await sandbox.wait_for_tasks(1)
    if ending == "result":
        await sandbox.reply(task["execution_id"], result_data="ok")
    elif ending == "stop":
        stop_event.set()
    elif ending == "cancelled":
        run.cancel()

    await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), timeout=5)

    assert run_python_code_service._pending_results == {}
