import asyncio
import json

import httpx
import pytest
from foundation.clients.sandbox import (
    ExecutionRequest,
    ExecutionStorageCredentials,
    SandboxClient,
    SandboxError,
    SandboxExecutionLostError,
    SandboxOverloadedError,
    SandboxResultTimeoutError,
    SandboxUnreachableError,
)
from foundation.clients.sandbox import client as client_module
from foundation.transport.http import ClientUnauthorizedError

EXECUTION_ID = "execution-1"
SECRET = "plaintext-secret-value"


class ScriptedSandbox:
    """A sandbox that answers each method from its own script; the last reply repeats.

    A reply is an `httpx.Response`, an httpx exception class to raise instead, or a
    function of the request that returns the response.
    """

    def __init__(self, *, post=(), get=()):
        self.scripts = {"POST": list(post), "GET": list(get)}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        script = self.scripts[request.method]
        assert script, f"unscripted {request.method} {request.url.path}"
        reply = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(reply, type):
            raise reply("scripted failure", request=request)
        if callable(reply):
            return reply(request)
        return reply

    def sent(self, method: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == method]


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        # A non-positive wait means the budget check let an attempt through past the deadline.
        assert seconds > 0, f"slept {seconds} s"
        self.sleeps.append(seconds)
        self.now += seconds


def respond(status_code: int, **kwargs) -> httpx.Response:
    return httpx.Response(status_code, **kwargs)


def overloaded(retry_after: str | None = None) -> httpx.Response:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return respond(503, headers=headers, json={"errors": [{"code": "overloaded"}]})


def known(status: str = "running") -> httpx.Response:
    return respond(200, json={"execution_id": EXECUTION_ID, "status": status})


def make_request() -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=EXECUTION_ID,
        code="def main(): return 1",
        entrypoint="main",
        secrets={"API_KEY": SECRET},
        use_storage=True,
        storage_org_prefix="org-1",
        storage_credentials=ExecutionStorageCredentials(access_key="access", secret_key=SECRET),
    )


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(client_module, "monotonic", fake.monotonic)
    monkeypatch.setattr(client_module, "sleep", fake.sleep)
    return fake


@pytest.fixture
async def connect():
    clients: list[SandboxClient] = []

    def factory(sandbox: ScriptedSandbox, queue_timeout: float = 60.0) -> SandboxClient:
        client = SandboxClient(
            queue_timeout=queue_timeout,
            base_url="http://sandbox",
            transport=httpx.MockTransport(sandbox),
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
def fast_status_polls(monkeypatch):
    monkeypatch.setattr(client_module, "STATUS_POLL_INTERVAL_SECONDS", 0.01)


# --- construction ---


@pytest.mark.parametrize("queue_timeout", [None, -1, -0.001, float("nan")])
def test_a_queue_timeout_that_is_not_zero_or_more_seconds_is_refused(queue_timeout):
    with pytest.raises(ValueError, match="queue_timeout"):
        SandboxClient(queue_timeout=queue_timeout, base_url="http://sandbox")


async def test_a_zero_queue_timeout_makes_a_single_attempt(clock, connect):
    sandbox = ScriptedSandbox(post=[overloaded("1")])

    with pytest.raises(SandboxOverloadedError):
        await connect(sandbox, queue_timeout=0).submit(make_request())

    assert len(sandbox.sent("POST")) == 1


# --- submit ---


async def test_submit_posts_the_request_and_returns_on_202(clock, connect):
    sandbox = ScriptedSandbox(post=[respond(202)])

    await connect(sandbox).submit(make_request())

    [post] = sandbox.sent("POST")
    assert post.url.path == "/executions"
    assert json.loads(post.content) == make_request().model_dump(mode="json")


async def test_submit_waits_at_least_retry_after_between_overloaded_attempts(clock, connect):
    sandbox = ScriptedSandbox(
        post=[overloaded(retry_after="5"), overloaded(retry_after="5"), respond(202)]
    )

    await connect(sandbox, queue_timeout=60).submit(make_request())

    assert len(sandbox.sent("POST")) == 3
    assert len(clock.sleeps) == 2
    assert all(seconds >= 5 for seconds in clock.sleeps)


async def test_submit_does_not_ask_for_status_when_no_attempt_went_unanswered(clock, connect):
    sandbox = ScriptedSandbox(post=[overloaded(), respond(202)], get=[known()])

    await connect(sandbox).submit(make_request())

    assert sandbox.sent("GET") == []


async def test_submit_raises_overloaded_once_the_queue_budget_is_spent(clock, connect):
    sandbox = ScriptedSandbox(post=[overloaded(retry_after="5")])

    with pytest.raises(SandboxOverloadedError, match=r"within 12 s"):
        await connect(sandbox, queue_timeout=12).submit(make_request())

    assert clock.sleeps == [5, 5, 2]
    assert len(sandbox.sent("POST")) == 4


@pytest.mark.parametrize("retry_after", ["soon", "-3", "inf", "nan", ""])
async def test_submit_falls_back_to_backoff_for_an_unusable_retry_after(
    clock, connect, retry_after
):
    sandbox = ScriptedSandbox(post=[overloaded(retry_after=retry_after), respond(202)])

    await connect(sandbox).submit(make_request())

    [seconds] = clock.sleeps
    assert 0 <= seconds <= client_module.BACKOFF_BASE_SECONDS


async def test_submit_retries_an_unanswered_attempt_with_the_same_execution(clock, connect):
    sandbox = ScriptedSandbox(post=[httpx.ReadTimeout, httpx.ConnectError, respond(202)])

    await connect(sandbox).submit(make_request())

    bodies = [post.content for post in sandbox.sent("POST")]
    assert len(bodies) == 3
    assert bodies[0] == bodies[1] == bodies[2]


@pytest.mark.parametrize("status_code", [502, 504])
async def test_submit_retries_a_gateway_error(clock, connect, status_code):
    sandbox = ScriptedSandbox(post=[respond(status_code), respond(202)])

    await connect(sandbox).submit(make_request())

    assert len(sandbox.sent("POST")) == 2


@pytest.mark.parametrize("final_status", [respond(404), httpx.ConnectError])
async def test_submit_raises_unreachable_once_the_budget_is_spent_and_the_sandbox_does_not_confirm(
    clock, connect, final_status
):
    sandbox = ScriptedSandbox(post=[httpx.ConnectError], get=[final_status])

    with pytest.raises(SandboxUnreachableError):
        await connect(sandbox, queue_timeout=5).submit(make_request())

    assert sum(clock.sleeps) == pytest.approx(5)
    assert len(sandbox.sent("GET")) == 1


async def test_submit_treats_an_unanswered_last_attempt_as_accepted_if_sandbox_knows_it(
    clock, connect
):
    sandbox = ScriptedSandbox(post=[httpx.ReadTimeout], get=[known("queued")])

    await connect(sandbox, queue_timeout=5).submit(make_request())

    assert sandbox.sent("GET")[0].url.path == f"/executions/{EXECUTION_ID}"


async def test_submit_does_not_ask_for_status_when_the_budget_ends_on_overloaded(clock, connect):
    sandbox = ScriptedSandbox(post=[overloaded()])

    with pytest.raises(SandboxOverloadedError):
        await connect(sandbox, queue_timeout=5).submit(make_request())

    assert sandbox.sent("GET") == []


async def test_submit_treats_overloaded_after_an_unanswered_attempt_as_accepted_if_sandbox_knows_it(
    clock, connect
):
    sandbox = ScriptedSandbox(post=[httpx.ReadTimeout, overloaded()], get=[known("queued")])

    await connect(sandbox).submit(make_request())

    assert len(sandbox.sent("POST")) == 2
    assert sandbox.sent("GET")[0].url.path == f"/executions/{EXECUTION_ID}"


async def test_submit_keeps_retrying_overloaded_after_an_unanswered_attempt_the_sandbox_does_not_know(
    clock, connect
):
    sandbox = ScriptedSandbox(
        post=[httpx.ReadTimeout, overloaded(), respond(202)], get=[respond(404)]
    )

    await connect(sandbox).submit(make_request())

    assert len(sandbox.sent("POST")) == 3


@pytest.mark.parametrize("status_code", [400, 404, 422, 500])
async def test_submit_raises_the_sandbox_refusal_at_once(clock, connect, status_code):
    body = '{"errors":[{"code":"venv_not_found","detail":"Venv 7 does not exist."}]}'
    sandbox = ScriptedSandbox(post=[respond(status_code, text=body)])

    with pytest.raises(SandboxError) as raised:
        await connect(sandbox).submit(make_request())

    assert type(raised.value) is SandboxError
    assert str(raised.value) == body
    assert len(sandbox.sent("POST")) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("reply", "error_type"),
    [(httpx.ConnectError, SandboxUnreachableError), (overloaded(), SandboxOverloadedError)],
)
async def test_submit_failure_never_shows_the_request_secrets(clock, connect, reply, error_type):
    sandbox = ScriptedSandbox(post=[reply], get=[respond(404)])

    with pytest.raises(error_type) as raised:
        await connect(sandbox, queue_timeout=1).submit(make_request())

    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value)


def test_execution_request_repr_hides_secrets_and_storage_credentials():
    assert SECRET not in repr(make_request())


# --- status ---


async def test_status_returns_the_status_the_sandbox_reports(connect):
    sandbox = ScriptedSandbox(get=[known("running")])

    assert await connect(sandbox).status(EXECUTION_ID) == "running"


async def test_status_quotes_the_execution_id_into_one_path_segment(connect):
    sandbox = ScriptedSandbox(get=[known("running")])

    await connect(sandbox).status("session/7")

    assert sandbox.sent("GET")[0].url.raw_path == b"/executions/session%2F7"


async def test_status_raises_lost_for_an_execution_the_sandbox_does_not_know(connect):
    sandbox = ScriptedSandbox(get=[respond(404)])

    with pytest.raises(SandboxExecutionLostError):
        await connect(sandbox).status(EXECUTION_ID)


# --- wait_for_result ---


async def test_wait_returns_a_fast_result_without_asking_for_status(connect):
    sandbox = ScriptedSandbox(get=[known()])

    async def result():
        return "output"

    received = await connect(sandbox).wait_for_result(EXECUTION_ID, result(), backstop=None)

    assert received == "output"
    assert sandbox.sent("GET") == []


async def test_wait_keeps_waiting_while_the_sandbox_reports_the_execution(
    connect, fast_status_polls
):
    sandbox = ScriptedSandbox(get=[known()])
    result = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_later(0.1, result.set_result, "output")

    assert await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None) == "output"
    assert len(sandbox.sent("GET")) >= 2


async def test_wait_raises_lost_when_the_sandbox_forgot_the_execution(connect, fast_status_polls):
    sandbox = ScriptedSandbox(get=[respond(404)])
    result = asyncio.get_running_loop().create_future()

    with pytest.raises(SandboxExecutionLostError):
        await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None)


async def test_wait_returns_a_result_that_arrives_together_with_a_404(connect, fast_status_polls):
    result = asyncio.get_running_loop().create_future()

    def forgotten_after_publishing(request: httpx.Request) -> httpx.Response:
        result.set_result("output")
        return respond(404)

    sandbox = ScriptedSandbox(get=[forgotten_after_publishing])

    received = await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None)

    assert received == "output"


async def test_wait_raises_unreachable_after_consecutive_status_failures(
    connect, fast_status_polls
):
    sandbox = ScriptedSandbox(
        get=[httpx.ConnectError, known(), httpx.ReadTimeout, respond(503), httpx.ConnectError]
    )
    result = asyncio.get_running_loop().create_future()

    with pytest.raises(SandboxUnreachableError):
        await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None)

    assert len(sandbox.sent("GET")) == 5


async def test_wait_propagates_a_status_refusal_that_is_not_transient(connect, fast_status_polls):
    sandbox = ScriptedSandbox(get=[respond(401)])
    result = asyncio.get_running_loop().create_future()

    with pytest.raises(ClientUnauthorizedError):
        await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None)


async def test_wait_raises_result_timeout_after_the_backstop(connect, fast_status_polls):
    sandbox = ScriptedSandbox(get=[known()])
    result = asyncio.get_running_loop().create_future()

    with pytest.raises(SandboxResultTimeoutError, match=r"after 0\.05 s"):
        await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=0.05)


class StopRequestedError(Exception):
    pass


@pytest.mark.parametrize("error_type", [StopRequestedError, TimeoutError])
async def test_wait_propagates_the_result_own_exception_unchanged(connect, error_type):
    async def result():
        raise error_type("stopped by the user")

    with pytest.raises(error_type, match="stopped by the user"):
        await connect(ScriptedSandbox()).wait_for_result(EXECUTION_ID, result(), backstop=10)


async def test_wait_cancels_the_pending_result_when_it_gives_up(connect, fast_status_polls):
    sandbox = ScriptedSandbox(get=[respond(404)])
    result = asyncio.get_running_loop().create_future()

    with pytest.raises(SandboxExecutionLostError):
        await connect(sandbox).wait_for_result(EXECUTION_ID, result, backstop=None)

    assert result.cancelled()


async def test_wait_cancels_the_pending_result_when_the_caller_is_cancelled(connect):
    result = asyncio.get_running_loop().create_future()
    waiting = asyncio.create_task(
        connect(ScriptedSandbox()).wait_for_result(EXECUTION_ID, result, backstop=None)
    )
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert result.cancelled()
