"""A placement's hooks: claimed from django_app (`httpx.MockTransport`), called on a real loopback
port, reported back.

The plugin's port is a small asyncio server that records each request and answers as a test
tells it; the process supervisor is a stand-in whose state a test sets.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from src.shared.models.plugin_nodes import HookInvocation, HookResult

from es_plugins.agent.django_client import DjangoNodeClient
from es_plugins.hooks import hook_runner as hook_runner_module
from es_plugins.hooks.hook_caller import MAX_HOOK_RESPONSE_BYTES, PluginHookCaller
from es_plugins.hooks.hook_runner import (
    RESTARTED_DURING_HOOK,
    STOPPED_DURING_HOOK,
    HookRunner,
    WrittenRuntimeFile,
    deliver_result,
)
from es_plugins.supervisor.process_supervisor import ProcessStatus
from tests.helpers import (
    API_URL,
    HOOK_ASSERTION,
    NODE_KEY,
    FakeDjango,
    free_port,
    hook_body,
    hook_invocation,
    hook_job,
    placement,
)
from tests.test_supervisor_backoff import wait_until

REVISION = "c" * 64


@dataclass(frozen=True)
class ReceivedRequest:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


Answer = Callable[[asyncio.StreamWriter], Awaitable[None]]


def answering(status: int, body: bytes | str, content_type: str = "application/json") -> Answer:
    payload = body.encode() if isinstance(body, str) else body

    async def answer(writer: asyncio.StreamWriter) -> None:
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        await writer.drain()

    return answer


async def never_answering(writer: asyncio.StreamWriter) -> None:
    await asyncio.Event().wait()


async def streaming_without_end(writer: asyncio.StreamWriter) -> None:
    """Announce 10 MiB, send twice the node's cap, then stall: only the cap may be read."""
    writer.write(b"HTTP/1.1 500 X\r\nContent-Length: 10485760\r\n\r\n")
    writer.write(b"x" * (2 * MAX_HOOK_RESPONSE_BYTES))
    await writer.drain()
    await asyncio.Event().wait()


class PluginPort:
    """A plugin process's port on the loopback."""

    def __init__(self):
        self.requests: list[ReceivedRequest] = []
        self.answer: Answer = answering(200, '{"status":"done"}')
        self.received = asyncio.Event()
        self.port: int | None = None
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        self._server.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
            method, target, _ = head[0].split(" ")
            headers = {
                name.lower(): value
                for name, _, value in (line.partition(": ") for line in head[1:] if line)
            }
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            self.requests.append(ReceivedRequest(method, target, headers, body))
            self.received.set()
            await self.answer(writer)
        finally:
            writer.close()


class SupervisorStandIn:
    """What a hook runner reads of the process supervisor."""

    def __init__(self):
        self.observed_state = "running"
        self.health = "ok"
        self.process: int | None = 1

    def status(self) -> ProcessStatus:
        return ProcessStatus(
            observed_state=self.observed_state,
            health=self.health,
            pid=4242,
            restarts=0,
            rss_mb=None,
            last_error=None,
            version="0.2.0",
        )

    def running_process(self) -> int | None:
        return self.process


@pytest.fixture
async def hooks():
    django = FakeDjango()
    client = DjangoNodeClient(API_URL, NODE_KEY, transport=django.transport)
    plugin = PluginPort()
    await plugin.start()
    caller = PluginHookCaller()
    supervisor = SupervisorStandIn()
    runners: list[HookRunner] = []

    def desired(jobs=(hook_job(),), **overrides):
        return placement(b"package", runtime__port=plugin.port, hook_jobs=list(jobs), **overrides)

    def runner(jobs=(hook_job(),), organizations=(3,), revision=REVISION, written=True, **overrides):
        started = HookRunner(desired(jobs, **overrides), supervisor, client, caller)
        if written:
            started.runtime_file_written(WrittenRuntimeFile(revision, frozenset(organizations)))
        started.start()
        runners.append(started)
        return started

    yield SimpleNamespace(
        django=django,
        client=client,
        plugin=plugin,
        caller=caller,
        supervisor=supervisor,
        desired=desired,
        runner=runner,
    )
    for started in runners:
        await started.close()
    await caller.aclose()
    await client.aclose()
    await plugin.close()


def invocation(**overrides) -> HookInvocation:
    return HookInvocation.model_validate(hook_invocation(**overrides))


async def test_a_claimed_hook_is_posted_to_the_plugin_as_is_and_its_success_reported(hooks):
    hooks.django.hook_invocations[41] = hook_invocation()

    hooks.runner()
    await wait_until(lambda: hooks.django.hook_results)

    assert hooks.django.requests_to("claim") == [41]
    request = hooks.plugin.requests[0]
    assert (request.method, request.target) == ("POST", "/_epicstaff/hooks/install")
    assert request.headers["x-epicstaff-hook"] == HOOK_ASSERTION
    assert request.headers["content-type"] == "application/json"
    assert request.body == hook_body().encode()
    job_id, result = hooks.django.hook_results[0]
    assert job_id == 41
    assert (result["attempt"], result["outcome"], result["error"], result["http_status"]) == (
        1,
        "succeeded",
        None,
        200,
    )
    assert result["duration_ms"] >= 0
    claim = next(request for request in hooks.django.requests if request.url.path.endswith("/claim/"))
    assert claim.url.path == "/api/plugin-nodes/self/hook-jobs/41/claim/"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (200, '{"status":"done","detail":"extra fields are fine"}', None),
        (200, '{"status":"running"}', "HTTP 200"),
        (200, "done", "HTTP 200"),
        (500, '{"status":"failed","error":{"message":"the flow could not be created"}}', "the flow could not be created"),
        (401, '{"status":"failed","error":{"message":"hook assertion rejected: expired"}}', "hook assertion rejected: expired"),
        (501, '{"status":"failed","error":{"message":"this plugin has no install hook"}}', "this plugin has no install hook"),
        (404, "<html>Not Found</html>", "HTTP 404"),
        (500, '{"error":{"message":42}}', "HTTP 500"),
        (500, '{"error":{"message":"\\u0000\\n"}}', "HTTP 500"),
        (502, "[" * 100_000, "HTTP 502"),
        (500, '{"error":{"message":"line one\\nline two\\u0007\\ud800 end"}}', "line one line two end"),
        (500, '{"error":{"message":"  spaced   out\\t "}}', "spaced out"),
    ],
)
async def test_what_the_plugin_answers_decides_the_outcome(hooks, status, body, error):
    hooks.plugin.answer = answering(status, body)

    outcome = await hooks.caller.call(hooks.plugin.port, invocation())

    assert (outcome.succeeded, outcome.error, outcome.http_status) == (error is None, error, status)


async def test_a_long_error_message_is_cut_to_what_django_app_stores(hooks):
    hooks.plugin.answer = answering(
        500, json.dumps({"status": "failed", "error": {"message": "\t" + "e" * 5000}})
    )

    outcome = await hooks.caller.call(hooks.plugin.port, invocation())

    assert outcome.error == "e" * 2000
    HookResult(attempt=1, outcome="failed", error=outcome.error, duration_ms=1)


async def test_a_plugin_that_does_not_answer_in_time_fails_the_hook(hooks):
    hooks.plugin.answer = never_answering

    outcome = await hooks.caller.call(hooks.plugin.port, invocation(timeout_seconds=1))

    assert (outcome.succeeded, outcome.error, outcome.http_status) == (
        False,
        "timed out after 1 s",
        None,
    )
    assert 1000 <= outcome.duration_ms < 3000


async def test_a_port_nobody_listens_on_fails_the_hook():
    caller = PluginHookCaller()

    outcome = await caller.call(free_port(), invocation())

    assert not outcome.succeeded
    assert outcome.error.startswith("could not connect: ")
    assert outcome.http_status is None
    await caller.aclose()


async def closing_without_an_answer(writer: asyncio.StreamWriter) -> None:
    writer.transport.abort()


async def answering_garbage(writer: asyncio.StreamWriter) -> None:
    writer.write(b"this is not HTTP\r\n\r\n")
    await writer.drain()


@pytest.mark.parametrize("answer", [closing_without_an_answer, answering_garbage])
async def test_a_connection_lost_after_connecting_fails_the_hook_as_lost(hooks, answer):
    hooks.plugin.answer = answer

    outcome = await hooks.caller.call(hooks.plugin.port, invocation())

    assert not outcome.succeeded
    assert outcome.error.startswith("the connection was lost: ")
    assert outcome.http_status is None


async def test_only_the_first_64_kib_of_an_answer_are_read(hooks):
    hooks.plugin.answer = streaming_without_end

    outcome = await asyncio.wait_for(
        hooks.caller.call(hooks.plugin.port, invocation(timeout_seconds=30)), 5
    )

    assert (outcome.succeeded, outcome.error, outcome.http_status) == (False, "HTTP 500", 500)


async def test_a_job_that_cannot_be_claimed_is_skipped_without_a_call(hooks):
    # No invocation for job 41: django_app answers its claim with 409.
    hooks.runner()
    await wait_until(lambda: hooks.django.requests_to("claim"))
    await asyncio.sleep(0.3)

    assert hooks.django.requests_to("claim") == [41]
    assert hooks.plugin.requests == []
    assert hooks.django.requests_to("result") == []


async def test_a_job_just_tried_is_claimed_again_only_after_a_while(hooks, monkeypatch):
    monkeypatch.setattr(hook_runner_module, "RECLAIM_AFTER_SECONDS", 0.5)

    hooks.runner()
    await wait_until(lambda: hooks.django.requests_to("claim"))
    await asyncio.sleep(0.3)
    assert hooks.django.requests_to("claim") == [41]

    await wait_until(lambda: len(hooks.django.requests_to("claim")) == 2, timeout=3)


async def test_a_job_that_left_the_list_and_came_back_is_claimed_again_at_once(hooks):
    runner = hooks.runner()
    await wait_until(lambda: hooks.django.requests_to("claim"))

    runner.update(hooks.desired(jobs=[]))
    hooks.django.hook_invocations[41] = hook_invocation(attempt=2)
    runner.update(hooks.desired())
    await wait_until(lambda: hooks.django.hook_results)

    assert hooks.django.requests_to("claim") == [41, 41]
    assert hooks.django.hook_results[0][1]["attempt"] == 2


@pytest.mark.parametrize(
    "not_ready",
    [
        "starting",
        "failing health",
        "organization not in the runtime file",
        "runtime file of another credentials revision",
        "no runtime file yet",
        "desired stopped",
    ],
)
async def test_a_job_waits_until_the_plugin_is_ready_for_it(hooks, not_ready):
    hooks.django.hook_invocations[41] = hook_invocation()
    supervisor = hooks.supervisor
    arguments = {}
    if not_ready == "starting":
        supervisor.observed_state, supervisor.health = "starting", "unknown"
    if not_ready == "failing health":
        supervisor.health = "failing"
    if not_ready == "organization not in the runtime file":
        arguments["organizations"] = (4,)
    if not_ready == "runtime file of another credentials revision":
        arguments["revision"] = "d" * 64
    if not_ready == "desired stopped":
        arguments["desired_state"] = "stopped"
    if not_ready == "no runtime file yet":
        arguments["written"] = False
    runner = hooks.runner(**arguments)

    await asyncio.sleep(0.3)
    assert hooks.django.requests_to("claim") == []

    supervisor.observed_state, supervisor.health = "running", "ok"
    runner.update(hooks.desired())
    runner.runtime_file_written(WrittenRuntimeFile(REVISION, frozenset({3})))
    await wait_until(lambda: hooks.django.hook_results)

    assert hooks.django.hook_results[0][1]["outcome"] == "succeeded"


async def test_the_oldest_job_goes_first_and_one_at_a_time(hooks):
    hooks.django.hook_invocations[41] = hook_invocation(41, 3)
    hooks.django.hook_invocations[42] = hook_invocation(42, 4)
    hooks.plugin.answer = answering(200, '{"status":"done"}')

    hooks.runner(jobs=[hook_job(41, 3), hook_job(42, 4)], organizations=(3, 4))
    await wait_until(lambda: len(hooks.django.hook_results) == 2)

    hook_requests = [
        request.url.path.split("/")[-2]
        for request in hooks.django.requests
        if "/hook-jobs/" in request.url.path
    ]
    assert hook_requests == ["claim", "result", "claim", "result"]
    assert [job_id for job_id, _ in hooks.django.hook_results] == [41, 42]


async def test_a_hook_whose_process_restarted_during_the_call_fails_with_that_reason(hooks):
    hooks.django.hook_invocations[41] = hook_invocation()

    async def restart_then_drop(writer):
        hooks.supervisor.process = None
        writer.transport.abort()

    hooks.plugin.answer = restart_then_drop
    hooks.runner()
    await wait_until(lambda: hooks.django.hook_results)

    result = hooks.django.hook_results[0][1]
    assert (result["outcome"], result["error"]) == ("failed", RESTARTED_DURING_HOOK)


async def test_a_hook_whose_process_converge_stopped_during_the_call_fails_as_stopped(hooks):
    hooks.django.hook_invocations[41] = hook_invocation()
    runners = []

    async def stop_then_drop(writer):
        # As the controller does: the new desired placement first, then converge stops it.
        runners[0].update(hooks.desired(desired_state="stopped"))
        hooks.supervisor.process = None
        writer.transport.abort()

    hooks.plugin.answer = stop_then_drop
    runners.append(hooks.runner())
    await wait_until(lambda: hooks.django.hook_results)

    result = hooks.django.hook_results[0][1]
    assert (result["outcome"], result["error"]) == ("failed", STOPPED_DURING_HOOK)


async def test_a_success_stands_even_if_the_process_restarts_right_after(hooks):
    hooks.django.hook_invocations[41] = hook_invocation()
    done = answering(200, '{"status":"done"}')

    async def answer_then_restart(writer):
        await done(writer)
        hooks.supervisor.process = 2

    hooks.plugin.answer = answer_then_restart
    hooks.runner()
    await wait_until(lambda: hooks.django.hook_results)

    assert hooks.django.hook_results[0][1]["outcome"] == "succeeded"


async def test_closing_the_runner_during_a_call_reports_the_hook_failed_once(hooks):
    hooks.django.hook_invocations[41] = hook_invocation()
    hooks.plugin.answer = never_answering
    runner = hooks.runner()
    await asyncio.wait_for(hooks.plugin.received.wait(), 5)

    await runner.close()

    assert len(hooks.django.hook_results) == 1
    result = hooks.django.hook_results[0][1]
    assert (result["outcome"], result["error"], result["http_status"]) == (
        "failed",
        STOPPED_DURING_HOOK,
        None,
    )


async def test_a_result_that_cannot_be_delivered_is_retried_for_up_to_120_seconds(hooks):
    hooks.django.failing_result_posts = 1000
    clock = SimpleNamespace(now=0.0)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    result = HookResult(attempt=1, outcome="succeeded", duration_ms=5)
    delivered = await deliver_result(
        hooks.client, 41, result, clock=lambda: clock.now, sleep=sleep
    )

    assert delivered is False
    # The last try is at 120 s; one more would be later.
    assert sleeps == [1, 2, 4, 8] + [15] * 7
    assert sum(sleeps) == 120
    assert hooks.django.requests_to("result") == [41] * 12


async def test_a_result_is_delivered_once_django_app_is_back(hooks):
    hooks.django.failing_result_posts = 2

    async def no_wait(seconds):
        pass

    result = HookResult(attempt=1, outcome="failed", error="boom", duration_ms=5)
    assert await deliver_result(hooks.client, 41, result, sleep=no_wait)

    assert hooks.django.hook_results == [(41, json.loads(result.model_dump_json()))]


async def test_a_refused_result_is_not_retried(hooks):
    hooks.django.failing_result_posts = 1000
    hooks.django.failing_result_status = 409

    result = HookResult(attempt=1, outcome="succeeded", duration_ms=5)
    assert await deliver_result(hooks.client, 41, result) is False

    assert hooks.django.requests_to("result") == [41]
