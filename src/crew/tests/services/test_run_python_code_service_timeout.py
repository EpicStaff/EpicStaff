"""run_code() waits for a result on a channel with no delivery guarantee.

It must give up after settings.CODE_RESULT_TIMEOUT, and leave no subscription
behind on any exit path.
"""

import asyncio

import pytest

import settings
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.run_python_code_service import TIMEOUT_STDERR_MESSAGE


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", 0.05)
    return 0.05


@pytest.mark.asyncio
async def test_run_code_returns_timeout_result_when_no_result_arrives(
    short_timeout, python_code_service, sandbox, make_python_code_data
):
    result = await asyncio.wait_for(
        python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["returncode"] == 124
    assert result["result_data"] is None
    assert result["execution_id"] == sandbox.submitted["execution_id"]
    assert result["stderr"] == TIMEOUT_STDERR_MESSAGE


@pytest.mark.asyncio
async def test_run_code_unsubscribes_exactly_once_on_timeout(
    short_timeout, python_code_service, redis, make_python_code_data
):
    await asyncio.wait_for(
        python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert redis.unsubscribe.call_count == 1
    assert redis.unsubscribe.call_args.kwargs["subscriber"] is redis.subscriber


@pytest.mark.asyncio
async def test_run_code_unsubscribes_when_stop_event_aborts_the_wait(
    short_timeout, python_code_service, redis, make_python_code_data
):
    stop_event = StopEvent()
    stop_event.set()

    with pytest.raises(StopSession):
        await asyncio.wait_for(
            python_code_service.run_code(
                python_code_data=make_python_code_data(),
                inputs={},
                stop_event=stop_event,
            ),
            timeout=5,
        )

    assert redis.unsubscribe.call_count == 1


@pytest.mark.asyncio
async def test_run_code_returns_the_sandbox_result_and_unsubscribes_once(
    run_code, redis, make_python_code_data
):
    result = await run_code(python_code_data=make_python_code_data(), inputs={})

    assert result["returncode"] == 0
    assert result["result_data"] == "ok"
    assert redis.unsubscribe.call_count == 1
