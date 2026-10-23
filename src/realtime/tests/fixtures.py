import json
import pytest
from unittest.mock import AsyncMock
import httpx
from application.tool_manager_service import ToolManagerService
from infrastructure.messaging.redis_service import RedisService
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from foundation.clients.sandbox import SandboxClient
from src.shared.models import RealtimeAgentChatData
from tool_executors.base_tool_executor import BaseToolExecutor
from tests.conftest import CONNECTION_KEY


class RecordingSandboxIntake:
    """Stands in for the sandbox HTTP API: records every submitted body and answers
    with `status_code`, so tests exercise the real client and the real request
    serialization and only the network is replaced. `GET /executions/{id}` reports
    every execution as running, or as unknown (404) once `loses_executions` is set."""

    BASE_URL = "http://sandbox.test"

    def __init__(self, status_code: int = 202):
        self.status_code = status_code
        self.bodies: list[dict] = []
        self.loses_executions = False

    def client(self, **httpx_options) -> SandboxClient:
        # No retry budget: a full or unreachable sandbox fails the first submit.
        httpx_options.setdefault("transport", httpx.MockTransport(self._handle))
        return SandboxClient(queue_timeout=0, base_url=self.BASE_URL, **httpx_options)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if self.loses_executions:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"status": "running"})
        assert request.url.path == "/executions"
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.status_code >= 400:
            return httpx.Response(self.status_code, json={"detail": "rejected"})
        return httpx.Response(
            self.status_code,
            json={"execution_id": body["execution_id"], "status": "pending"},
        )


class FakeTokenizer:
    """Returns one token per character — no tiktoken download needed in tests."""

    def tokenize(self, text: str) -> list[int]:
        return list(range(len(text)))

    def detokenize(self, tokens) -> str:
        return "x" * len(tokens)


class DummyToolExecutor(BaseToolExecutor):
    def __init__(self, name="dummy_tool"):
        super().__init__(tool_name=name)
        self.executed_with = None

    async def execute(self, **kwargs):
        self.executed_with = kwargs
        return {"status": "ok", "tool": self.tool_name, "args": kwargs}

    async def get_realtime_tool_model(self):
        return {"name": self.tool_name, "type": "mock"}



@pytest.fixture
def sample_chat_data() -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key=CONNECTION_KEY,
        org_id=1,
        rt_api_key="fake_key",
        rt_model_name="test_model",
        wake_word="wake",
        voice="voice1",
        temperature=0.5,
        language="en",
        goal="assist user",
        backstory="helpful assistant",
        role="assistant",
        transcript_api_key="transcript_api_key",
        transcript_model_name="whisper",
        voice_recognition_prompt="say something",
        knowledge_collection_id=1,
        similarity_threshold=0.2,
        memory=True,
        stop_prompt="stop",
        tools=[],
        python_code_tools=[],
    )


@pytest.fixture
def redis_service():
    return RedisService(
        host="localhost",
        port=6379,
        password="redis_password",
    )


@pytest.fixture
def sandbox_intake() -> RecordingSandboxIntake:
    return RecordingSandboxIntake()


@pytest.fixture
def tool_manager(redis_service, sandbox_intake) -> ToolManagerService:
    return ToolManagerService(
        python_code_executor_service=PythonCodeExecutorService(
            redis_service, sandbox_intake.client()
        ),
        knowledge_client=AsyncMock(),
    )
