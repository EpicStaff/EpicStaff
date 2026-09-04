from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from dotdict import DotDict

from services.graph.nodes.agent_node import AgentNode
from src.shared.models import (
    AgentDefinitionData,
    AgentNodeData,
    AgentNodeTaskData,
    LLMConfigData,
    LLMData,
)
from src.shared.redis_streams import StreamEnvelope


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
def agent_node_data(llm_data) -> AgentNodeData:
    return AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1,
            name="researcher",
            instructions="Research the topic.",
            llm=llm_data,
        ),
        tasks=[
            AgentNodeTaskData(
                name="task_a", order=0, instructions="Write about {topic}"
            ),
            AgentNodeTaskData(
                name="task_b",
                order=1,
                instructions="Summarize {topic} findings",
                context_tasks=["task_a"],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_execute_returns_result_dict(agent_node_data):
    agent_task_service = AsyncMock()
    agent_task_service.run_agent_node.return_value = {
        "final_text": "The summary.",
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
        "tasks": [
            {
                "name": "task_a",
                "order": 0,
                "final_text": "A done",
                "token_usage": {"total_tokens": 10},
                "iterations": 2,
                "tool_invocations": 1,
                "stop_reason": "completed",
            }
        ],
    }

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
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
        "tasks": [
            {
                "name": "task_a",
                "order": 0,
                "message": "A done",
                "token_usage": {"total_tokens": 10},
                "iterations": 2,
                "tool_invocations": 1,
            }
        ],
    }
    agent_task_service.run_agent_node.assert_awaited_once_with(
        mock.ANY, node.stop_event, on_event=mock.ANY
    )


@pytest.mark.asyncio
async def test_execute_returns_empty_tasks_when_payload_lacks_tasks_key(
    agent_node_data,
):
    """Old agent service without the 'tasks' key should degrade gracefully."""
    agent_task_service = AsyncMock()
    agent_task_service.run_agent_node.return_value = {
        "final_text": "The summary.",
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
    }

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    result = await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    assert result["tasks"] == []


@pytest.mark.asyncio
async def test_run_interpolates_instructions_for_every_task(llm_data):
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        tasks=[
            AgentNodeTaskData(
                name="task_a", order=0, instructions="Write about {topic}"
            ),
            AgentNodeTaskData(
                name="task_b",
                order=1,
                instructions="Summarize {topic} findings",
                context_tasks=["task_a"],
            ),
        ],
        input_map={"topic": "variables.topic"},
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_agent_node.return_value = {"final_text": "done"}

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    state = make_state({"topic": "cats"})
    await node.run(state=state, writer=MagicMock())

    dispatched_data = agent_task_service.run_agent_node.await_args.args[0]
    assert dispatched_data.tasks[0].instructions == "Write about cats"
    assert dispatched_data.tasks[1].instructions == "Summarize cats findings"
    # original node data is untouched
    assert agent_node_data.tasks[0].instructions == "Write about {topic}"


@pytest.mark.asyncio
async def test_execute_forwards_live_agent_events_as_agent_node_stream(
    agent_node_data,
):
    agent_task_service = AsyncMock()

    async def fake_run_agent_node(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.task_start",
                correlation_id="corr-1",
                payload={"task": {"name": "task_a", "order": 0}},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.tool_call",
                correlation_id="corr-1",
                payload={"id": "call_1", "name": "search", "arguments": "{}"},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.tool_result",
                correlation_id="corr-1",
                payload={"tool_call_id": "call_1", "content": "result"},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.task_finish",
                correlation_id="corr-1",
                payload={"task": {"name": "task_a", "order": 0}, "message": "done"},
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_agent_node.side_effect = fake_run_agent_node

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "agent_node_stream"
    ]

    assert len(stream_messages) == 4
    assert [message["event"] for message in stream_messages] == [
        "task_start",
        "tool_call",
        "tool_result",
        "task_finish",
    ]
    assert [message["step_id"] for message in stream_messages] == [1, 2, 3, 4]
    assert stream_messages[0]["data"]["task"] == {"name": "task_a", "order": 0}
    assert stream_messages[3]["data"]["task"] == {"name": "task_a", "order": 0}


@pytest.mark.asyncio
async def test_execute_forwards_knowledge_search_envelope_as_extracted_chunks(
    agent_node_data,
):
    agent_task_service = AsyncMock()
    knowledge_payload = {
        "collection_id": 7,
        "rag_id": 3,
        "rag_type": "naive",
        "retrieved_chunks": 2,
        "knowledge_query": "What is EpicStaff?",
        "rag_search_config": {"top_k": 2},
        "chunks": [{"text": "chunk one"}, {"text": "chunk two"}],
        "token_usage": {"total_tokens": 15},
    }

    async def fake_run_agent_node(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.knowledge_search",
                correlation_id="corr-1",
                payload=knowledge_payload,
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_agent_node.side_effect = fake_run_agent_node

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    extracted_chunks_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "extracted_chunks"
    ]

    assert len(extracted_chunks_messages) == 1
    message = extracted_chunks_messages[0]
    for key, value in knowledge_payload.items():
        assert message[key] == value


@pytest.mark.asyncio
async def test_execute_knowledge_search_envelope_does_not_shift_stream_step_id(
    agent_node_data,
):
    agent_task_service = AsyncMock()

    async def fake_run_agent_node(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.task_start",
                correlation_id="corr-1",
                payload={"task": {"name": "task_a", "order": 0}},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.tool_call",
                correlation_id="corr-1",
                payload={"id": "call_1", "name": "search", "arguments": "{}"},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.knowledge_search",
                correlation_id="corr-1",
                payload={"collection_id": 7, "chunks": []},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.tool_result",
                correlation_id="corr-1",
                payload={"tool_call_id": "call_1", "content": "result"},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.task_finish",
                correlation_id="corr-1",
                payload={"task": {"name": "task_a", "order": 0}, "message": "done"},
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_agent_node.side_effect = fake_run_agent_node

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "agent_node_stream"
    ]

    assert [message["event"] for message in stream_messages] == [
        "task_start",
        "tool_call",
        "tool_result",
        "task_finish",
    ]
    assert [message["step_id"] for message in stream_messages] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_execute_drops_unknown_envelope_type_and_writes_no_message(
    agent_node_data,
):
    agent_task_service = AsyncMock()

    async def fake_run_agent_node(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.heartbeat",
                correlation_id="corr-1",
                payload={},
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_agent_node.side_effect = fake_run_agent_node

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "agent_node_stream"
    ]

    assert stream_messages == []


@pytest.mark.asyncio
async def test_execute_raises_when_agent_definition_missing():
    agent_node_data = AgentNodeData(node_name="agent_node_1", agent_definition=None)
    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=AsyncMock(),
    )

    with pytest.raises(ValueError, match="agent_definition"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )


@pytest.mark.asyncio
async def test_execute_raises_when_llm_missing():
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(id=1, name="researcher"),
    )
    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=AsyncMock(),
    )

    with pytest.raises(ValueError, match="llm"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )


@pytest.mark.asyncio
async def test_run_stores_message_text_at_output_variable_path(llm_data):
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        tasks=[AgentNodeTaskData(name="task_a", order=0, instructions="Write.")],
        output_variable_path="variables.result",
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_agent_node.return_value = {"final_text": "The summary."}

    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=agent_task_service,
    )

    assert node.output_variable_path == "variables.result"

    state = make_state({})
    await node.run(state=state, writer=MagicMock())

    assert state["variables"].result == "The summary."


@pytest.mark.asyncio
async def test_execute_raises_when_tasks_empty(llm_data):
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        tasks=[],
    )
    node = AgentNode(
        session_id=1,
        node_name="agent_node_1",
        stop_event=MagicMock(),
        agent_node_data=agent_node_data,
        agent_task_service=AsyncMock(),
    )

    with pytest.raises(ValueError, match="no tasks"):
        await node.execute(
            state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
        )
