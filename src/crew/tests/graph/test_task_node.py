from unittest import mock

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.shared.redis_streams import StreamEnvelope

from dotdict import DotDict

from services.graph.nodes.task_node import TaskNode
from src.shared.models import AgentDefinitionData, LLMConfigData, LLMData, TaskNodeData


def make_state(variables: dict) -> dict:
    return {
        "state_history": [],
        "variables": DotDict(variables),
        "system_variables": {},
    }


def make_remembered_outputs_store(fetch_all_return_value: list | None = None):
    store = AsyncMock()
    store.fetch_all.return_value = fetch_all_return_value or []
    return store


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
        remembered_outputs_store=make_remembered_outputs_store(),
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
        task_node_data, node.stop_event, on_event=mock.ANY
    )


@pytest.mark.asyncio
async def test_execute_forwards_live_agent_events_as_task_node_stream(task_node_data):
    agent_task_service = AsyncMock()

    async def fake_run_task(node_data, stop_event, on_event=None):
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
        return {"final_text": "done"}

    agent_task_service.run_task.side_effect = fake_run_task

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "task_node_stream"
    ]

    assert len(stream_messages) == 2
    assert stream_messages[0]["event"] == "tool_call"
    assert stream_messages[0]["step_id"] == 1
    assert stream_messages[0]["is_final"] is False
    assert stream_messages[0]["data"] == {
        "id": "call_1",
        "name": "search",
        "arguments": "{}",
    }
    assert stream_messages[1]["event"] == "tool_result"
    assert stream_messages[1]["step_id"] == 2


@pytest.mark.asyncio
async def test_execute_forwards_task_lifecycle_events_as_task_node_stream(
    task_node_data,
):
    """SINGLE_TASK doesn't emit agent.task_start today, but the translation
    from envelope type to stream event is generic, so feed one synthetically
    to prove the mapping isn't tool-event-only."""
    agent_task_service = AsyncMock()

    async def fake_run_task(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.task_start",
                correlation_id="corr-1",
                payload={"task": {"name": "task_node_1", "order": 0}},
            )
        )
        on_event(
            StreamEnvelope(
                type="agent.tool_call",
                correlation_id="corr-1",
                payload={"id": "call_1", "name": "search", "arguments": "{}"},
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_task.side_effect = fake_run_task

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "task_node_stream"
    ]

    assert len(stream_messages) == 2
    assert stream_messages[0]["event"] == "task_start"
    assert stream_messages[0]["step_id"] == 1
    assert stream_messages[0]["data"]["task"] == {"name": "task_node_1", "order": 0}
    assert stream_messages[1]["event"] == "tool_call"
    assert stream_messages[1]["step_id"] == 2


@pytest.mark.asyncio
async def test_execute_forwards_knowledge_search_envelope_as_extracted_chunks(
    task_node_data,
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

    async def fake_run_task(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.knowledge_search",
                correlation_id="corr-1",
                payload=knowledge_payload,
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_task.side_effect = fake_run_task

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
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
    task_node_data,
):
    agent_task_service = AsyncMock()

    async def fake_run_task(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.task_start",
                correlation_id="corr-1",
                payload={"task": {"name": "task_node_1", "order": 0}},
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
                payload={
                    "task": {"name": "task_node_1", "order": 0},
                    "message": "done",
                },
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_task.side_effect = fake_run_task

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "task_node_stream"
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
    task_node_data,
):
    agent_task_service = AsyncMock()

    async def fake_run_task(node_data, stop_event, on_event=None):
        on_event(
            StreamEnvelope(
                type="agent.heartbeat",
                correlation_id="corr-1",
                payload={},
            )
        )
        return {"final_text": "done"}

    agent_task_service.run_task.side_effect = fake_run_task

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    writer = MagicMock()
    state = make_state({})
    await node.run(state=state, writer=writer)

    stream_messages = [
        call.args[0].message_data
        for call in writer.call_args_list
        if isinstance(call.args[0].message_data, dict)
        and call.args[0].message_data.get("message_type") == "task_node_stream"
    ]

    assert stream_messages == []


@pytest.mark.asyncio
async def test_execute_raises_when_agent_definition_missing():
    task_node_data = TaskNodeData(node_name="task_node_1", agent_definition=None)
    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=AsyncMock(),
        remembered_outputs_store=make_remembered_outputs_store(),
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
        remembered_outputs_store=make_remembered_outputs_store(),
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
        remembered_outputs_store=make_remembered_outputs_store(),
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
        remembered_outputs_store=make_remembered_outputs_store(),
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
        remembered_outputs_store=make_remembered_outputs_store(),
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
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    state = make_state({})
    await node.run(state=state, writer=MagicMock())

    called_data = agent_task_service.run_task.await_args.args[0]
    assert called_data.instructions == 'Return JSON like {"a": 1}'


@pytest.mark.asyncio
async def test_execute_stores_output_when_remember_output_true(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Summarize.",
        remember_output=True,
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "The summary."}
    remembered_outputs_store = make_remembered_outputs_store()

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=remembered_outputs_store,
    )

    await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    remembered_outputs_store.store.assert_awaited_once_with(
        1, "task_node_1", "The summary."
    )


@pytest.mark.asyncio
async def test_execute_does_not_store_output_when_remember_output_false(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Summarize.",
        remember_output=False,
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "The summary."}
    remembered_outputs_store = make_remembered_outputs_store()

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=remembered_outputs_store,
    )

    await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    remembered_outputs_store.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_does_not_store_when_final_text_empty(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Summarize.",
        remember_output=True,
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": ""}
    remembered_outputs_store = make_remembered_outputs_store()

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=remembered_outputs_store,
    )

    await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    remembered_outputs_store.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_stores_message_text_at_output_variable_path(llm_data):
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=llm_data
        ),
        instructions="Summarize.",
        output_variable_path="variables.result",
    )
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "The summary."}

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=make_remembered_outputs_store(),
    )

    assert node.output_variable_path == "variables.result"

    state = make_state({})
    await node.run(state=state, writer=MagicMock())

    assert state["variables"].result == "The summary."


@pytest.mark.asyncio
async def test_execute_prepends_remembered_outputs_to_instructions(task_node_data):
    agent_task_service = AsyncMock()
    agent_task_service.run_task.return_value = {"final_text": "done"}
    remembered_outputs_store = make_remembered_outputs_store(
        [("earlier_task", "earlier output")]
    )

    node = TaskNode(
        session_id=1,
        node_name="task_node_1",
        stop_event=MagicMock(),
        task_node_data=task_node_data,
        agent_task_service=agent_task_service,
        remembered_outputs_store=remembered_outputs_store,
    )

    await node.execute(
        state=MagicMock(), writer=MagicMock(), execution_order=0, input_={}
    )

    called_data = agent_task_service.run_task.await_args.args[0]
    assert called_data.instructions.startswith("===== PREVIOUS TASKS OUTPUTS =====")
    assert "Task 'earlier_task':\nearlier output" in called_data.instructions
    assert called_data.instructions.endswith(task_node_data.instructions)
    assert task_node_data.instructions == "Summarize the findings."
