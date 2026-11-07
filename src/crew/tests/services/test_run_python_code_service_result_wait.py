"""RunPythonCodeService waits for the sandbox's result on crew's own result channel.

One subscription per process parses each result once and hands it to the
execution waiting for it; a wait ends on the result, the timeout, or a stop.
"""

import asyncio
import json

import fakeredis
import pytest
import pytest_asyncio
from loguru import logger

import settings
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.redis_service import RedisService
from services.run_python_code_service import RunPythonCodeService
from src.shared.models import CodeFailure, CodeFailureCode, CodeResultData
from tests.services.conftest import CREW_RESULT_CHANNEL, SHARED_RESULT_CHANNEL
from utils.singleton_meta import SingletonMeta

pytestmark = pytest.mark.asyncio


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
    redis_service_on_fakeredis, fake_server, sandbox, sandbox_client, make_python_code_data
):
    """The result path works over real pub/sub, not only over the in-memory double."""
    service = RunPythonCodeService(
        redis_service=redis_service_on_fakeredis, sandbox_client=sandbox_client
    )
    await service.subscribe_to_results()
    sandbox_redis = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

    run = asyncio.ensure_future(
        service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    try:
        [task] = await sandbox.wait_for_tasks(1)
        await sandbox_redis.publish(
            CREW_RESULT_CHANNEL,
            CodeResultData(
                execution_id=task["execution_id"], result_data="42", stderr="", stdout=""
            ).model_dump_json(),
        )
        result = await asyncio.wait_for(run, timeout=5)
    finally:
        run.cancel()
        await sandbox_redis.aclose()

    assert result.result_data == "42"
    assert result.returncode == 0


async def test_returns_the_result_the_sandbox_publishes_for_the_execution(
    run_python_code_service, sandbox, make_python_code_data
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.reply(task["execution_id"], result_data="ok")

    result = await asyncio.wait_for(run, timeout=5)

    assert task["reply_to_crew_channel"] is True
    assert result.execution_id == task["execution_id"]
    assert result.result_data == "ok"
    assert result.returncode == 0


async def test_returns_a_result_published_before_the_wait_starts(
    run_python_code_service, sandbox, make_python_code_data
):
    sandbox.auto_reply = True

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result.execution_id == sandbox.tasks[0]["execution_id"]
    assert result.result_data == "ok"


async def test_returns_timeout_result_when_no_result_arrives(
    run_python_code_service, sandbox, short_timeout, make_python_code_data
):
    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    timeout_text = (
        "The code's result didn't arrive in time. Try again or contact your administrator."
    )
    assert result == CodeResultData(
        execution_id=sandbox.tasks[0]["execution_id"],
        returncode=1,
        stdout="",
        stderr=timeout_text,
        result_data=None,
        failure=CodeFailure(code=CodeFailureCode.RESULT_TIMEOUT, detail=timeout_text),
        reference=None,
    )


async def test_waits_until_the_result_when_timeout_is_none(
    run_python_code_service, sandbox, monkeypatch, make_python_code_data
):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await asyncio.sleep(0.05)
    await sandbox.reply(task["execution_id"], result_data="late")

    result = await asyncio.wait_for(run, timeout=5)

    assert result.result_data == "late"


async def test_stop_event_set_during_the_wait_aborts_it(
    run_python_code_service, sandbox, make_python_code_data
):
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
    run_python_code_service,
    sandbox,
    pubsub,
    short_timeout,
    channel,
    foreign_execution_id,
    make_python_code_data,
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

    assert result.failure.code is CodeFailureCode.RESULT_TIMEOUT
    assert result.result_data is None


async def test_unparseable_message_is_dropped_and_the_wait_continues(
    run_python_code_service, sandbox, pubsub, make_python_code_data
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await pubsub.apublish(CREW_RESULT_CHANNEL, "not json")
    await sandbox.reply(task["execution_id"], result_data="ok")

    result = await asyncio.wait_for(run, timeout=5)

    assert result.result_data == "ok"


async def test_concurrent_executions_each_get_their_own_result_from_one_subscription(
    run_python_code_service, sandbox, pubsub, make_python_code_data
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

    assert [result.result_data for result in results] == [
        result.execution_id for result in results
    ]
    assert len({result.execution_id for result in results}) == 3
    assert len(pubsub.subscribers[CREW_RESULT_CHANNEL]) == 1


@pytest.mark.parametrize("ending", ["result", "timeout", "stop", "cancelled"])
async def test_wait_leaves_no_pending_execution_behind(
    run_python_code_service, sandbox, short_timeout, ending, make_python_code_data
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


RAW_OUTPUT = "secret output of the user's code"


@pytest.mark.parametrize(
    "failure",
    [
        # A code crew doesn't know is read as unknown, not rejected: see test_code_failure.
        pytest.param(
            {"code": "user_code_error", "detail": RAW_OUTPUT}, id="user-error-without-its-parts"
        ),
        pytest.param(
            {"code": "unexpected_argument", "detail": RAW_OUTPUT}, id="argument-code-without-attr"
        ),
    ],
)
async def test_result_that_fails_validation_fails_the_execution_at_once_under_a_reference(
    run_python_code_service, sandbox, pubsub, make_python_code_data, monkeypatch, failure
):
    monkeypatch.setattr("foundation.utils.error_reference.new_reference", lambda: "0a1b2c3d4e5f")
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="ERROR")
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    try:
        [task] = await sandbox.wait_for_tasks(1)
        await pubsub.apublish(
            CREW_RESULT_CHANNEL,
            json.dumps(
                {
                    "execution_id": task["execution_id"],
                    "stdout": RAW_OUTPUT,
                    "stderr": RAW_OUTPUT,
                    "returncode": 1,
                    "failure": failure,
                }
            ),
        )
        result = await asyncio.wait_for(run, timeout=5)
    finally:
        run.cancel()
        logger.remove(sink_id)

    public_text = "Node execution failed (reference: 0a1b2c3d4e5f)"
    assert result == CodeResultData(
        execution_id=task["execution_id"],
        returncode=1,
        stdout="",
        stderr=public_text,
        result_data=None,
        failure=CodeFailure(code=CodeFailureCode.SANDBOX_ERROR, detail=public_text),
        reference="0a1b2c3d4e5f",
    )
    [line] = [record for record in logged if "(reference: 0a1b2c3d4e5f)" in record]
    assert task["execution_id"] in line
    assert "ValidationError" in line
    assert RAW_OUTPUT not in "".join(logged)
