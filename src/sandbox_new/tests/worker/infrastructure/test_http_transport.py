"""Behavior of the worker's two network adapters.

The job source keeps polling through empty answers and transport failures and hands
back a decoded domain job. The result sink guarantees an outcome for every send: the
result is delivered, a fixed replacement failure is delivered when the manager refuses
the body, or the process is taken down (401/403, or the manager unreachable past the
retries) so the restart's new boot id lets the manager fail the stranded jobs. Both are
tested against a mock HTTP transport, never a real socket; process termination is a
recorded fake.
"""

import httpx
import pytest

from common.contracts import ExecutionJobMessage, ExecutionResultMessage
from foundation.transport.http import AsyncClient
from worker.application.ports import UndecodableJobError
from worker.domain.models import ExecutionResult
from worker.infrastructure.transport.http_job_source import HttpJobSource
from worker.infrastructure.transport.http_result_sink import HttpResultSink

JOB = ExecutionJobMessage(
    execution_id="exec-9",
    venv_hash="4abc",
    code="def main():\n    return 2",
    entrypoint="main",
    secrets={"TOKEN": "s3cret"},
    session_id=11,
    queued_at=1_800_000_000.0,
)


class Script:
    """Answers each request with the next scripted response and records the requests."""

    def __init__(self, *responses: httpx.Response | Exception):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class RecordingStop:
    """Stands in for ``terminate_process``, which would SIGTERM the test run."""

    def __init__(self) -> None:
        self.called = False

    def __call__(self) -> None:
        self.called = True


def client_for(script: Script) -> AsyncClient:
    # The boot id lives on the client's default headers, the way worker/main.py sets it.
    return AsyncClient(
        base_url="http://manager:8090",
        transport=httpx.MockTransport(script),
        headers={"X-Worker-Boot-Id": "boot-1"},
    )


def job_response() -> httpx.Response:
    return httpx.Response(200, content=JOB.model_dump_json())


async def test_a_pulled_job_is_decoded_and_carries_the_boot_id():
    script = Script(job_response())

    job = await HttpJobSource(client_for(script)).get()

    assert job.execution_id == "exec-9"
    assert job.secrets == {"TOKEN": "s3cret"}
    assert job.queued_at == 1_800_000_000.0
    assert script.requests[0].url.path == "/worker/jobs"
    assert script.requests[0].headers["X-Worker-Boot-Id"] == "boot-1"


async def test_an_empty_poll_is_asked_again():
    script = Script(httpx.Response(204), job_response())

    job = await HttpJobSource(client_for(script)).get()

    assert job.execution_id == "exec-9"
    assert len(script.requests) == 2


async def test_a_failed_poll_is_retried():
    script = Script(httpx.ConnectError("refused"), httpx.Response(500), job_response())

    source = HttpJobSource(client_for(script), retry_delay=0.001)
    job = await source.get()

    assert job.execution_id == "exec-9"
    assert len(script.requests) == 3


async def test_a_refused_token_takes_the_process_down_instead_of_retrying():
    script = Script(httpx.Response(401))
    stop = RecordingStop()

    source = HttpJobSource(client_for(script), retry_delay=0.001, stop=stop)
    with pytest.raises(Exception):
        await source.get()

    assert stop.called is True
    assert len(script.requests) == 1


async def test_a_body_that_is_not_a_job_is_dropped_and_polling_goes_on():
    script = Script(httpx.Response(200, content=b'{"no": "job"}'), job_response())

    source = HttpJobSource(client_for(script), retry_delay=0.001)
    job = await source.get()

    assert job.execution_id == "exec-9"


async def test_a_wire_job_that_does_not_decode_raises_undecodable():
    broken = ExecutionJobMessage.model_construct(
        execution_id="exec-1",
        venv_hash=None,
        code="",
        entrypoint="main",
        secrets={"TOKEN": "s3cret"},
        reply_to_crew_channel=True,
        session_id=11,
    )
    script = Script(httpx.Response(200, content=broken.model_dump_json()))

    with pytest.raises(UndecodableJobError) as raised:
        await HttpJobSource(client_for(script)).get()

    assert raised.value.execution_id == "exec-1"
    assert "s3cret" not in str(raised.value)


async def test_a_result_is_posted_to_the_manager():
    script = Script(httpx.Response(202))

    await HttpResultSink(client_for(script)).send(
        ExecutionResult(execution_id="exec-9", stdout="ok", ran=True)
    )

    request = script.requests[0]
    assert request.url.path == "/worker/results"
    assert request.headers["X-Worker-Boot-Id"] == "boot-1"
    assert b'"execution_id":"exec-9"' in request.content
    assert b'"ran":true' in request.content


async def test_a_failed_delivery_is_retried():
    script = Script(httpx.ConnectError("refused"), httpx.Response(202))

    sink = HttpResultSink(client_for(script), retry_delay=0.001)
    await sink.send(ExecutionResult(execution_id="exec-9", ran=True))

    assert len(script.requests) == 2


async def test_a_refused_body_is_replaced_with_a_fixed_failure_result():
    script = Script(httpx.Response(413), httpx.Response(202))
    stop = RecordingStop()

    sink = HttpResultSink(client_for(script), retry_delay=0.001, stop=stop)
    await sink.send(
        ExecutionResult(
            execution_id="exec-9", result="x" * 100, session_id=11, reply_to_crew_channel=True
        )
    )

    assert stop.called is False
    replacement = ExecutionResultMessage.model_validate_json(script.requests[1].content)
    assert replacement.execution_id == "exec-9"
    assert replacement.returncode == 1
    assert replacement.stderr == "Sandbox could not deliver the execution result."
    assert replacement.result is None
    assert replacement.session_id == 11
    assert replacement.reply_to_crew_channel is True


async def test_a_refused_replacement_takes_the_process_down():
    script = Script(httpx.Response(413), httpx.Response(413))
    stop = RecordingStop()

    sink = HttpResultSink(client_for(script), retry_delay=0.001, stop=stop)
    await sink.send(ExecutionResult(execution_id="exec-9", ran=True))

    assert stop.called is True


async def test_an_unreachable_manager_takes_the_process_down_after_the_retry_budget():
    script = Script(*[httpx.ConnectError("refused")] * 10)
    stop = RecordingStop()

    sink = HttpResultSink(
        client_for(script), retry_budget=0.005, retry_delay=0.001, stop=stop
    )
    await sink.send(ExecutionResult(execution_id="exec-9", ran=True))

    assert len(script.requests) >= 2
    assert stop.called is True


async def test_a_refused_token_on_delivery_takes_the_process_down_without_a_replacement():
    script = Script(httpx.Response(401))
    stop = RecordingStop()

    sink = HttpResultSink(client_for(script), retry_delay=0.001, stop=stop)
    await sink.send(ExecutionResult(execution_id="exec-9", ran=True))

    assert stop.called is True
    assert len(script.requests) == 1
async def test_a_server_error_is_retried_without_stopping_the_worker():
    """A 503 is a manager hiccup, not a refusal of the body: stopping here would kill
    every running execution over a blip the liveness model tolerates."""
    script = Script(httpx.Response(503), httpx.Response(202))
    stop = RecordingStop()

    sink = HttpResultSink(client_for(script), retry_delay=0.001, stop=stop)
    await sink.send(ExecutionResult(execution_id="exec-9", ran=True))

    assert len(script.requests) == 2
    assert stop.called is False


async def test_a_server_error_then_a_refused_body_still_sends_the_replacement():
    script = Script(httpx.Response(503), httpx.Response(413), httpx.Response(202))
    stop = RecordingStop()

    sink = HttpResultSink(client_for(script), retry_delay=0.001, stop=stop)
    await sink.send(ExecutionResult(execution_id="exec-9", session_id=11, ran=True))

    assert stop.called is False
    replacement = ExecutionResultMessage.model_validate_json(script.requests[2].content)
    assert replacement.execution_id == "exec-9"
    assert replacement.stderr == "Sandbox could not deliver the execution result."
    assert replacement.session_id == 11
