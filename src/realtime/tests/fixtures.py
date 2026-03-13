from fastapi import WebSocket
import pytest
from unittest.mock import AsyncMock
from services.tool_manager_service import ToolManagerService
from services.redis_service import RedisService
from services.python_code_executor_service import PythonCodeExecutorService
from src.shared.models import RealtimeAgentChatData
from tool_executors.base_tool_executor import BaseToolExecutor
from tests.conftest import CONNECTION_KEY


class DummyToolExecutor(BaseToolExecutor):
    def __init__(self, name="dummy_tool"):
        super().__init__(tool_name=name)
        self.executed_with = None

    async def execute(self, **kwargs):
        self.executed_with = kwargs
        return {"status": "ok", "tool": self.tool_name, "args": kwargs}

    async def get_realtime_tool_model(self):
        return {"name": self.tool_name, "type": "mock"}


@pytest.mark.asyncio
@pytest.fixture
def mock_ws_client():
    # Creating a mock WebSocket client
    ws_client = AsyncMock(spec=WebSocket)
    ws_client.send_json = AsyncMock()
    ws_client.receive_json = AsyncMock(
        return_value={"type": "response", "message": "Hello, user!"}
    )
    return ws_client


@pytest.fixture
def sample_chat_data() -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key=CONNECTION_KEY,
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
def tool_manager(redis_service) -> ToolManagerService:
    return ToolManagerService(
        redis_service=redis_service,
        python_code_executor_service=PythonCodeExecutorService(redis_service),
        knowledge_search_get_channel="knowledge:search:get",
        knowledge_search_response_channel="knowledge:search:response",
        manager_host="localhost",
        manager_port=8080,
    )


@pytest.mark.asyncio
@pytest.fixture
def mock_ws_client():
    # Creating a mock WebSocket client
    ws_client = AsyncMock(spec=WebSocket)

    return ws_client
