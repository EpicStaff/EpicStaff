"""An execution the sandbox never produces a result for fails the node instead of hanging.

The sandbox can stay full, be unreachable, or lose an execution it accepted (a
restart, an undelivered result). Each ends the wait with a returncode-1 result whose
`error` tells the user why, coded by the failure, and whose stderr stays empty; only the
backstop keeps the timeout returncode. A session
stop ends a submit that is still retrying a full sandbox instead of waiting out its
retry budget.
"""

import asyncio

import httpx
import pytest

import settings
from clients import sandbox as sandbox_client_module
from clients.sandbox import SandboxClient
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from services.run_python_code_service import (
    STOP_CHECK_INTERVAL_S,
    RunPythonCodeService,
    code_failure_text,
)
from tests.services.conftest import (
    CREW_RESULT_CHANNEL,
    REJECTED_RETRY_AFTER_S,
    SANDBOX_BASE_URL,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fast_status_checks(monkeypatch):
    monkeypatch.setattr(sandbox_client_module, "STATUS_POLL_INTERVAL_SECONDS", 0.01)


@pytest.mark.parametrize(
    ("sandbox_state", "expected_error"),
    [
        (
            "full",
            {"code": "overloaded", "detail": "The server was too busy to run the code in time."},
        ),
        (
            "unreachable",
            {"code": "sandbox_unreachable", "detail": "The code couldn't run because of a server error."},
        ),
    ],
)
async def test_submit_the_sandbox_does_not_take_fails_the_execution(
    run_python_code_service, sandbox, make_python_code_data, sandbox_state, expected_error
):
    setattr(sandbox, sandbox_state, True)

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["returncode"] == 1
    assert result["error"] == expected_error
    assert result["stderr"] == ""
    assert result["result_data"] is None


async def test_execution_the_sandbox_lost_fails_instead_of_waiting_for_the_backstop(
    run_python_code_service, sandbox, make_python_code_data, fast_status_checks, monkeypatch
):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    sandbox.loses_executions = True

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert result["execution_id"] == sandbox.submitted["execution_id"]
    assert result["returncode"] == 1
    assert result["error"] == {
        "code": "execution_lost",
        "detail": "The code couldn't run because of a server error.",
    }
    assert result["stderr"] == ""


HTML_BAD_GATEWAY = "<html><body>502 Bad Gateway from internal-proxy:8080</body></html>"
SERVER_TRACEBACK = '{"type": "server_error", "errors": [{"code": "unknown", "detail": "/app/x.py"}]}'


@pytest.mark.parametrize(
    ("answer", "expected_error"),
    [
        (
            httpx.Response(
                409,
                json={
                    "type": "client_error",
                    "errors": [{"code": "venv_failed", "detail": "Venv 3 failed to build."}],
                },
            ),
            {"code": "venv_failed", "detail": "Venv 3 failed to build."},
        ),
        (
            httpx.Response(500, text=SERVER_TRACEBACK),
            {"code": "server_error", "detail": "The code couldn't run because of a server error."},
        ),
        (
            httpx.Response(500, text=HTML_BAD_GATEWAY),
            {"code": "server_error", "detail": "The code couldn't run because of a server error."},
        ),
        (
            httpx.Response(500),
            {"code": "server_error", "detail": "The code couldn't run because of a server error."},
        ),
    ],
    ids=["4xx-envelope", "5xx-envelope", "5xx-html", "5xx-empty"],
)
async def test_a_refused_submit_shows_only_a_fact_the_sandbox_meant_for_the_user(
    run_python_code_service, sandbox, make_python_code_data, answer, expected_error
):
    sandbox.submit_answer = answer

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert (result["returncode"], result["error"], result["stderr"]) == (1, expected_error, "")


async def test_a_status_check_the_sandbox_refuses_fails_the_execution_with_the_generic_fact(
    run_python_code_service, sandbox, make_python_code_data, fast_status_checks, monkeypatch
):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    sandbox.status_answer = httpx.Response(401, text=HTML_BAD_GATEWAY)

    result = await asyncio.wait_for(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={}),
        timeout=5,
    )

    assert (result["returncode"], result["error"], result["stderr"]) == (
        1,
        {"code": "server_error", "detail": "The code couldn't run because of a server error."},
        "",
    )


async def test_execution_the_sandbox_still_has_keeps_waiting_for_its_result(
    run_python_code_service, sandbox, make_python_code_data, fast_status_checks
):
    run = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    # Several status checks pass while the execution is still running.
    await asyncio.sleep(0.05)
    assert not run.done()

    await sandbox.reply(task["execution_id"], result_data="late")
    result = await asyncio.wait_for(run, timeout=5)

    assert (result["returncode"], result["result_data"]) == (0, "late")


async def test_a_stop_while_the_sandbox_stays_full_cancels_the_retrying_submit(
    pubsub, sandbox, make_python_code_data, monkeypatch
):
    # Retries every few milliseconds, so a submit that kept going would show up at once.
    monkeypatch.setattr(sandbox_client_module, "BACKOFF_CAP_SECONDS", 0.01)
    sandbox.full = True
    service = RunPythonCodeService(
        redis_service=pubsub,
        sandbox_client=SandboxClient(
            queue_timeout=60,
            base_url=SANDBOX_BASE_URL,
            transport=httpx.MockTransport(sandbox.handle),
        ),
    )
    await service.subscribe_to_results()
    stop_event = StopEvent()
    run = asyncio.ensure_future(
        service.run_code(
            python_code_data=make_python_code_data(), inputs={}, stop_event=stop_event
        )
    )
    await sandbox.wait_for_tasks(2)
    loop = asyncio.get_running_loop()

    stopped_at = loop.time()
    stop_event.set()
    with pytest.raises(StopSession):
        await asyncio.wait_for(run, timeout=5)
    interrupted_after = loop.time() - stopped_at
    attempts_at_stop = len(sandbox.tasks)
    await asyncio.sleep(0.1)

    assert interrupted_after < STOP_CHECK_INTERVAL_S + 0.25
    assert len(sandbox.tasks) == attempts_at_stop


def of_type(checkpoints: list[dict], name: str) -> list[dict]:
    return [item for item in checkpoints if item["checkpoint"] == name]


async def test_a_503_followed_by_a_retry_is_logged_as_sandbox_rejected(
    pubsub, sandbox, make_python_code_data, checkpoints, monkeypatch
):
    # The jittered backoff stays under Retry-After, so the logged wait is exactly it.
    monkeypatch.setattr(sandbox_client_module, "BACKOFF_CAP_SECONDS", 0.001)
    sandbox.rejections_left = 1
    sandbox.auto_reply = True
    service = RunPythonCodeService(
        redis_service=pubsub,
        sandbox_client=SandboxClient(
            queue_timeout=60,
            base_url=SANDBOX_BASE_URL,
            transport=httpx.MockTransport(sandbox.handle),
        ),
    )
    await service.subscribe_to_results()

    result = await asyncio.wait_for(
        service.run_code(python_code_data=make_python_code_data(session_id=5), inputs={}),
        timeout=5,
    )

    assert result["returncode"] == 0
    assert of_type(checkpoints, "sandbox_rejected") == [
        {
            "checkpoint": "sandbox_rejected",
            "session_id": 5,
            "execution_id": sandbox.tasks[0]["execution_id"],
            "attempt": 1,
            "retry_after_s": REJECTED_RETRY_AFTER_S,
        }
    ]


async def test_an_execution_the_sandbox_lost_is_logged_as_sandbox_lost(
    run_python_code_service,
    sandbox,
    make_python_code_data,
    fast_status_checks,
    checkpoints,
    monkeypatch,
):
    monkeypatch.setattr(settings, "CODE_RESULT_TIMEOUT", None)
    sandbox.loses_executions = True

    await asyncio.wait_for(
        run_python_code_service.run_code(
            python_code_data=make_python_code_data(session_id=5), inputs={}
        ),
        timeout=5,
    )

    assert of_type(checkpoints, "sandbox_lost") == [
        {
            "checkpoint": "sandbox_lost",
            "session_id": 5,
            "execution_id": sandbox.submitted["execution_id"],
        }
    ]


async def test_a_sandbox_error_with_an_extra_field_still_reaches_the_node(
    run_python_code_service, sandbox, make_python_code_data
):
    running = asyncio.ensure_future(
        run_python_code_service.run_code(python_code_data=make_python_code_data(), inputs={})
    )
    [task] = await sandbox.wait_for_tasks(1)
    await sandbox.pubsub.apublish(
        CREW_RESULT_CHANNEL,
        {
            "execution_id": task["execution_id"],
            "result_data": None,
            "stdout": "",
            "stderr": "",
            "returncode": 1,
            "error": {"code": "worker_lost", "detail": "Sandbox worker was lost; the job may not have finished.", "attr": None},
        },
    )

    result = await asyncio.wait_for(running, timeout=5)

    assert code_failure_text(result) == "Sandbox worker was lost; the job may not have finished."
