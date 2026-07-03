import pytest
from unittest.mock import AsyncMock, MagicMock

from dotdict import DotDict

from services.graph.nodes.task_node import TaskNode
from src.shared.models import AgentDefinitionData, LLMConfigData, LLMData, TaskNodeData


def make_state(variables: dict) -> dict:
    return {
        "state_history": [],
        "variables": DotDict(variables),
        "system_variables": {},
    }


@pytest.fixture
def llm_data() -> LLMData:
    return LLMData(provider="openai", config=LLMConfigData(model="gpt-4o"))


@pytest.fixture
def task_node_data(llm_data) -> TaskNodeData:
    return TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1,
            name="researcher",
            instructions="Research the topic.",
            llm=llm_data,
        ),
        instructions="Summarize the findings.",
    )


@pytest.mark.asyncio
async def test_execute_returns_result_dict(task_node_data):
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {
        "final_text": "The summary.",
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
    }

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
    )

    result = await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    assert result == {
        "message": "The summary.",
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
    }
    agent_task_service.run_task.assert_awaited_once_with(
        task_node_data, node.stop_event
    )


@pytest.mark.asyncio
async def test_execute_raises_when_agent_definition_missing():
    task_node_data = TaskNodeData(node_name="task_node_1", agent_definition=None)
    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=AsyncMock(),
    )

    with pytest.raises(ValueError, match="agent_definition"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )


@pytest.mark.asyncio
async def test_execute_raises_when_llm_missing():
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(id=1, name="researcher"),
    )
    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=AsyncMock(),
    )

    with pytest.raises(ValueError, match="llm"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )


@pytest.mark.asyncio
async def test_execute_propagates_service_exception(task_node_data):
    agent_task_service = AsyncMock()
    agent_task_service.run_task.side_effect = RuntimeError("agent unreachable")

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
    )

    with pytest.raises(RuntimeError, match="agent unreachable"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )


@pytest.mark.asyncio
async def test_run_interpolates_instructions_from_input_map(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Write about {topic}",
        input_map={"topic": "variables.topic"},
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "done"}

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
    )

    state = make_state({"topic": "cats"})
    await node.run(state=state, writer=MagicMock())

    called_data = agent_task_service.run_task.await_args.args[0]
    assert called_data.instructions == "Write about cats"
    assert task_node_data.instructions == "Write about {topic}"


@pytest.mark.asyncio
async def test_run_leaves_unknown_placeholder_untouched(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Write about {missing}",
        input_map={},
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "done"}

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
    )

    state = make_state({})
    await node.run(state=state, writer=MagicMock())

    called_data = agent_task_service.run_task.await_args.args[0]
    assert called_data.instructions == "Write about {missing}"


@pytest.mark.asyncio
async def test_run_sends_json_example_instructions_verbatim(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions='Return JSON like {"a": 1}',
        input_map={},
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "done"}

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
    )

    state = make_state({})
    await node.run(state=state, writer=MagicMock())

    called_data = agent_task_service.run_task.await_args.args[0]
    assert called_data.instructions == 'Return JSON like {"a": 1}'
