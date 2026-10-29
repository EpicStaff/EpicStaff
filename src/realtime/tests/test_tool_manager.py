import pytest
from unittest.mock import MagicMock

from tests.fixtures import DummyToolExecutor
from tests.conftest import CONNECTION_KEY


@pytest.mark.parametrize(
    ("with_controller", "rag_type_id", "expected_tools"),
    [
        (True, "naive:2", {"stop_agent_tool", "knowledge_tool"}),
        # A collection is only searchable once its RAG type is known.
        (True, None, {"stop_agent_tool"}),
        # ElevenLabs has its own VAD, so no mode controller and no stop tool.
        (False, "naive:2", {"knowledge_tool"}),
    ],
    ids=["both", "collection-without-rag-type", "no-mode-controller"],
)
def test_built_in_tools_are_registered_for_the_session(tool_manager, sample_chat_data, with_controller, rag_type_id, expected_tools):
    from src.shared.models import NaiveRagSearchConfig

    sample_chat_data.rag_type_id = rag_type_id
    sample_chat_data.rag_search_config = NaiveRagSearchConfig()

    tool_manager.register_tools_from_rt_agent_chat_data(
        sample_chat_data, chat_mode_controller=MagicMock() if with_controller else None
    )

    executors = tool_manager.connection_tool_executors[CONNECTION_KEY]
    assert {executor.tool_name for executor in executors} == expected_tools


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
                    code="def main(**kw): return kw",
                    entrypoint="main",
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


