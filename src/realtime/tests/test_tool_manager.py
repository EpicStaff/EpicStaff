import pytest
from unittest.mock import MagicMock

from tests.fixtures import *
from tests.conftest import CONNECTION_KEY


def test_register_tools(tool_manager, sample_chat_data):
    tool_manager.connection_tool_executors = {}
    tool_manager.register_tools_from_rt_agent_chat_data(
        sample_chat_data, chat_mode_controller=MagicMock()
    )

    assert CONNECTION_KEY in tool_manager.connection_tool_executors
    executors = tool_manager.connection_tool_executors[CONNECTION_KEY]
    assert any(
        exec.tool_name == "stop_agent_tool" or exec.tool_name == "knowledge_tool"
        for exec in executors
    )


@pytest.mark.asyncio
async def test_execute_matching_tool(tool_manager):
    tool = DummyToolExecutor(name="custom_tool")
    tool_manager.connection_tool_executors[CONNECTION_KEY] = [tool]

    result = await tool_manager.execute(
        CONNECTION_KEY, "custom_tool", {"query": "test input"}
    )

    assert result["status"] == "ok"
    assert result["tool"] == "custom_tool"
    assert result["args"]["query"] == "test input"


@pytest.mark.asyncio
async def test_execute_unknown_tool(tool_manager):
    tool = DummyToolExecutor(name="known_tool")
    tool_manager.connection_tool_executors[CONNECTION_KEY] = [tool]

    result = await tool_manager.execute(CONNECTION_KEY, "missing_tool", {})

    assert result == "missing_tool not found"


@pytest.mark.asyncio
async def test_get_realtime_tool_models(tool_manager):
    tool1 = DummyToolExecutor(name="t1")
    tool2 = DummyToolExecutor(name="t2")
    tool_manager.connection_tool_executors[CONNECTION_KEY] = [tool1, tool2]

    models = await tool_manager.get_realtime_tool_models(CONNECTION_KEY)

    assert len(models) == 2
    assert models[0]["name"] == "t1"
    assert models[1]["name"] == "t2"


def test_register_tools_with_storage_credentials(tool_manager, sample_chat_data):
    """storage_credentials on rt_agent_chat_data reaches each registered
    PythonCodeToolExecutor -- not just "no errors on registration"."""
    from src.shared.models import (
        BaseToolData,
        PythonCodeData,
        PythonCodeToolData,
        StorageCredentials,
    )
    from tool_executors import PythonCodeToolExecutor

    storage_credentials = StorageCredentials(access_key="test-access", secret_key="test-secret")
    sample_chat_data.storage_credentials = storage_credentials
    sample_chat_data.tools = [
        BaseToolData(
            unique_name="python-code-tool:1",
            data=PythonCodeToolData(
                id=1,
                name="Storage Tool",
                description="",
                python_code=PythonCodeData(
                    venv_name="venv_1",
                    code="def main(**kw): return kw",
                    entrypoint="main",
                    libraries=[],
                    use_storage=True,
                    storage_allowed_paths=["realtime/sessions/"],
                ),
            ),
        )
    ]

    tool_manager.connection_tool_executors = {}
    tool_manager.register_tools_from_rt_agent_chat_data(
        sample_chat_data, chat_mode_controller=MagicMock()
    )

    executors = tool_manager.connection_tool_executors[CONNECTION_KEY]
    python_code_executors = [e for e in executors if isinstance(e, PythonCodeToolExecutor)]
    assert len(python_code_executors) == 1
    assert python_code_executors[0].storage_credentials is storage_credentials


