"""Doubles shared by the RunPythonCodeService tests.

The sandbox is a real SandboxClient over an httpx MockTransport, so a test sees
the JSON body crew actually submits to sandbox_new's intake. Results still come
back on the Redis code-results channel, replayed here on demand.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from clients.sandbox import SandboxClient
from services.run_python_code_service import RunPythonCodeService
from src.shared.models import CodeResultData, PythonCodeData
from utils.singleton_meta import SingletonMeta

SANDBOX_BASE_URL = "http://sandbox:8000"


class RecordingSandbox:
    """sandbox_new's intake: records the body of every submitted execution.

    Setting `rejects_with` makes every submit answer 400 with that text, the way
    sandbox_new refuses an execution it will not run.
    """

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.rejects_with: str | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if self.rejects_with is not None:
            return httpx.Response(400, text=self.rejects_with)
        return httpx.Response(202, json={"status": "accepted"})

    @property
    def submitted(self) -> dict[str, Any]:
        """The one execution submitted so far."""
        assert len(self.bodies) == 1, f"expected one submitted execution, got {len(self.bodies)}"
        return self.bodies[0]

    async def wait_for_submit(self) -> dict[str, Any]:
        async with asyncio.timeout(5):
            while not self.bodies:
                await asyncio.sleep(0)
        return self.submitted


class FakeRedisService:
    """The code-results channel: replays a result to whoever run_code subscribed."""

    def __init__(self) -> None:
        self.asubscribe = AsyncMock()
        self.unsubscribe = MagicMock()

    @property
    def subscriber(self):
        return self.asubscribe.await_args.kwargs["subscriber"]

    async def deliver_result(self, execution_id: str, result_data: str = "ok") -> None:
        result = CodeResultData(
            execution_id=execution_id,
            result_data=result_data,
            stdout="",
            stderr="",
            returncode=0,
        )
        await self.subscriber.update(message={"data": result.model_dump_json()})


@pytest.fixture(autouse=True)
def _reset_singleton():
    """RunPythonCodeService is a process-wide singleton (utils/singleton_meta.py).

    Reset it around every test so an instance built with the fakes above does not
    leak into or out of other test modules.
    """
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


@pytest.fixture
def sandbox() -> RecordingSandbox:
    return RecordingSandbox()


@pytest.fixture
def sandbox_client(sandbox: RecordingSandbox) -> SandboxClient:
    return SandboxClient(
        base_url=SANDBOX_BASE_URL, transport=httpx.MockTransport(sandbox.handle)
    )


@pytest.fixture
def redis() -> FakeRedisService:
    return FakeRedisService()


@pytest.fixture
def python_code_service(redis: FakeRedisService, sandbox_client: SandboxClient):
    return RunPythonCodeService(redis_service=redis, sandbox_client=sandbox_client)


@pytest.fixture
def make_python_code_data():
    def make(**overrides) -> PythonCodeData:
        defaults = dict(
            venv_name="default",
            code="def main(**kw): return kw",
            entrypoint="main",
            libraries=[],
            global_kwargs={},
        )
        defaults.update(overrides)
        return PythonCodeData(**defaults)

    return make


@pytest.fixture
def run_code(python_code_service, redis: FakeRedisService, sandbox: RecordingSandbox):
    """Run run_code() and answer the submitted execution with a successful result."""

    async def run(result_data: str = "ok", **run_code_kwargs) -> dict[str, Any]:
        running = asyncio.ensure_future(python_code_service.run_code(**run_code_kwargs))
        submitted = await sandbox.wait_for_submit()
        await redis.deliver_result(submitted["execution_id"], result_data=result_data)
        return await asyncio.wait_for(running, timeout=5)

    return run
