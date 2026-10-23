"""realtime hands a code execution to the sandbox over HTTP and correlates the
result that comes back on the Redis result channel. The HTTP intake is the real
client over a mock transport (`RecordingSandboxIntake`), so the body asserted
here is the body that would go on the wire."""

import asyncio

import httpx
import pytest

from core import config
from domain.ports.i_redis_messaging_service import IRedisMessagingService
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from infrastructure.sandbox.sandbox_client import SandboxExecutionClient
from src.shared.models import CodeResultData, PythonCodeData
from tests.fixtures import RecordingSandboxIntake
from utils.singleton_meta import SingletonMeta


class FakePubSub:
    def __init__(self, intake: RecordingSandboxIntake):
        self._intake = intake
        self.closed = False

    async def get_message(self, ignore_subscribe_messages: bool, timeout: float):
        # run_code submits before it polls; failing here beats an endless poll loop.
        assert self._intake.bodies, "run_code polled without submitting a task"
        submitted = self._intake.bodies[-1]
        result = CodeResultData(
            execution_id=submitted["execution_id"],
            result_data="ok",
            stderr="",
            stdout="",
        )
        return {"data": result.model_dump_json()}

    async def aclose(self):
        self.closed = True


class FakeRedisMessagingService(IRedisMessagingService):
    """Answers the result subscription with a result for the submitted task."""

    def __init__(self, intake: RecordingSandboxIntake):
        self.intake = intake
        self.published: list[tuple[str, object]] = []
        self.subscribed_channels: list[str] = []
        self.subscriptions: list[FakePubSub] = []

    async def async_subscribe(self, channel: str):
        self.subscribed_channels.append(channel)
        pubsub = FakePubSub(self.intake)
        self.subscriptions.append(pubsub)
        return pubsub

    async def async_publish(self, channel: str, message: object) -> None:
        self.published.append((channel, message))


@pytest.fixture(autouse=True)
def reset_singleton():
    """Drop only this service's instance; clearing the whole dict would orphan
    module-level singletons that `api.main` holds (see test_voice_stream_handler)."""
    SingletonMeta._instances.pop(PythonCodeExecutorService, None)
    yield
    SingletonMeta._instances.pop(PythonCodeExecutorService, None)


@pytest.fixture
def fake_redis_service(sandbox_intake):
    yield FakeRedisMessagingService(sandbox_intake)


@pytest.fixture
def executor(fake_redis_service, sandbox_intake):
    yield PythonCodeExecutorService(fake_redis_service, sandbox_intake.client())


def build_python_code_data(**overrides) -> PythonCodeData:
    fields = {
        "code": "def main(): return 'ok'",
        "entrypoint": "main",
    }
    fields.update(overrides)
    return PythonCodeData(**fields)


def submitted_task(sandbox_intake: RecordingSandboxIntake) -> dict:
    assert len(sandbox_intake.bodies) == 1
    return sandbox_intake.bodies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("org_id", "code_globals", "caller_globals", "expected_globals"),
    [
        (42, {}, None, {"org_id": 42}),
        (None, {}, None, {}),
        (7, {"graph_id": 3, "api_key": "key"}, {"session_id": 11}, {"graph_id": 3, "api_key": "key", "session_id": 11, "org_id": 7}),
        # The resolved org always wins: tools send it as X-Organization-Id to Django.
        (7, {"org_id": 999}, {"org_id": 998}, {"org_id": 7}),
    ],
    ids=["org", "no-org", "kept-globals", "org-cannot-be-spoofed"],
)
async def test_code_task_carries_the_org_into_the_sandbox(
    executor, sandbox_intake, org_id, code_globals, caller_globals, expected_globals
):
    python_code_data = build_python_code_data(org_id=org_id, global_kwargs=code_globals)

    result = await executor.run_code(python_code_data, inputs={"query": "hello"}, additional_global_kwargs=caller_globals)

    task = submitted_task(sandbox_intake)
    assert (task["global_kwargs"], task["func_kwargs"]) == (expected_globals, {"query": "hello"})
    assert result["result_data"] == "ok"


@pytest.mark.asyncio
async def test_submitted_body_is_the_intake_contract(executor, sandbox_intake):
    python_code_data = build_python_code_data(
        venv_id=17, code="def main(**kw): return kw", secrets={"API_KEY": "sk-live-123"}
    )

    result = await executor.run_code(python_code_data, inputs={"query": "hello"})

    task = submitted_task(sandbox_intake)
    assert task == {
        "execution_id": result["execution_id"],
        "session_id": None,
        "code": "def main(**kw): return kw",
        "entrypoint": "main",
        "global_kwargs": {},
        "func_kwargs": {"query": "hello"},
        "secrets": {"API_KEY": "sk-live-123"},
        "venv_id": 17,
        "use_storage": False,
        "storage_allowed_paths": [],
        "storage_org_prefix": None,
        "storage_credentials": None,
        "timeout": None,
    }


@pytest.mark.asyncio
async def test_venv_id_is_null_when_the_code_declares_none(executor, sandbox_intake):
    """None addresses the sandbox's default venv; an omitted venv_id used to be
    the only thing realtime ever sent, so every run landed there."""
    await executor.run_code(build_python_code_data(), inputs={})

    assert submitted_task(sandbox_intake)["venv_id"] is None


@pytest.mark.asyncio
async def test_the_code_execution_does_not_go_over_redis(executor, fake_redis_service):
    await executor.run_code(build_python_code_data(), inputs={})

    assert fake_redis_service.published == []
    assert fake_redis_service.subscribed_channels == [config.CODE_RESULT_CHANNEL]


@pytest.mark.asyncio
async def test_rejected_submit_fails_the_run_instead_of_waiting_for_a_result(sandbox_intake):
    """No result will ever arrive for a submission the sandbox refused, so the
    correlation loop must not be entered at all."""
    sandbox_intake.status_code = 500
    redis_service = FakeRedisMessagingService(sandbox_intake)
    executor = PythonCodeExecutorService(redis_service, sandbox_intake.client())

    result = await asyncio.wait_for(
        executor.run_code(build_python_code_data(), inputs={}), timeout=5
    )

    assert result["returncode"] == 1
    assert result["stderr"] == "Could not reach the code sandbox for this run."
    assert result["stdout"] == ""


@pytest.mark.asyncio
async def test_unreachable_sandbox_fails_the_run(sandbox_intake, captured_log_messages):
    """A connect error carries the request -- and its secrets -- so the log may
    name only the error class."""

    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = SandboxExecutionClient(
        base_url=RecordingSandboxIntake.BASE_URL, transport=httpx.MockTransport(refuse)
    )
    executor = PythonCodeExecutorService(FakeRedisMessagingService(sandbox_intake), client)

    result = await asyncio.wait_for(
        executor.run_code(
            build_python_code_data(secrets={"API_KEY": "sk-live-SENTINEL"}), inputs={}
        ),
        timeout=5,
    )

    assert result["returncode"] == 1
    assert "sk-live-SENTINEL" not in "".join(captured_log_messages)
    assert "ConnectError" in "".join(captured_log_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [202, 500], ids=["result-arrives", "submit-refused"])
async def test_the_result_subscription_is_closed_on_every_exit(sandbox_intake, status_code):
    """One subscription per execution would otherwise outlive the call and pile up
    for the process's lifetime."""
    sandbox_intake.status_code = status_code
    redis_service = FakeRedisMessagingService(sandbox_intake)
    executor = PythonCodeExecutorService(redis_service, sandbox_intake.client())

    await asyncio.wait_for(executor.run_code(build_python_code_data(), inputs={}), timeout=5)

    [subscription] = redis_service.subscriptions
    assert subscription.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_timeout", [42, None], ids=["tool-timeout", "sandbox-default"])
async def test_submission_carries_the_tool_execution_timeout(
    executor, sandbox_intake, execution_timeout
):
    """The code's own timeout reaches the sandbox as the intake's `timeout`; None
    lets the sandbox apply its default."""
    python_code_data = build_python_code_data(execution_timeout=execution_timeout)

    await executor.run_code(python_code_data, inputs={})

    assert submitted_task(sandbox_intake)["timeout"] == execution_timeout
