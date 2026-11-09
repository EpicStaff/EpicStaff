"""AgentNode and TaskNode: both dispatch work to the agent service, forward its live
events to the session stream and store the result in the flow's variables.

The agent service is a separate microservice, so it is replaced by a fake that emits
the envelopes a real run would; everything else (message writer, remembered-outputs
store on fake Redis, variable mapping) is real.
"""

import re
import types

import fakeredis
import pytest
from dotdict import DotDict
from loguru import logger

from services.graph.events import StopEvent
from services.graph.exceptions import InvalidStatePathError
from services.graph.nodes.agent_node import AgentNode
from services.graph.nodes.task_node import TaskNode
from services.graph.remembered_outputs import RememberedOutputsStore
from src.shared.flow_templates import RefusedPlaceholderError
from src.shared.models import (
    AgentDefinitionData,
    AgentNodeData,
    AgentNodeTaskData,
    LLMConfigData,
    LLMData,
    TaskNodeData,
)
from src.shared.models.storage_scope import StorageCredentials
from src.shared.redis_streams import StreamEnvelope

pytestmark = pytest.mark.asyncio

SESSION_ID = 1
AGENT = AgentDefinitionData(
    id=1,
    name="researcher",
    instructions="Research the topic.",
    llm=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
)


class FakeAgentService:
    """Stands in for the agent microservice: emits `events`, returns `result`."""

    def __init__(self, result=None, events=(), error=None):
        self.result = result if result is not None else {"final_text": "done"}
        self.events = events
        self.error = error
        self.dispatched = None
        self.storage_credentials = None

    async def _run(self, node_data, stop_event, on_event=None, storage_credentials=None):
        self.dispatched = node_data
        self.storage_credentials = storage_credentials
        for envelope_type, payload in self.events:
            on_event(StreamEnvelope(type=envelope_type, correlation_id="corr-1", payload=payload))
        if self.error is not None:
            raise self.error
        return self.result

    run_task = _run
    run_agent_node = _run


@pytest.fixture
def remembered_outputs():
    redis_service = types.SimpleNamespace(
        aioredis_client=fakeredis.FakeAsyncRedis(decode_responses=True)
    )
    return RememberedOutputsStore(redis_service=redis_service)


def _task_node(service, store, storage_credentials=None, **data):
    node_data = TaskNodeData(
        **{"node_name": "task_node_1", "agent_definition": AGENT, "instructions": "Summarize.", **data}
    )
    return TaskNode(
        session_id=SESSION_ID,
        node_name="task_node_1",
        stop_event=StopEvent(),
        task_node_data=node_data,
        agent_task_service=service,
        remembered_outputs_store=store,
        storage_credentials=storage_credentials,
    )


def _agent_node(service, store, storage_credentials=None, **data):
    node_data = AgentNodeData(
        **{
            "node_name": "agent_node_1",
            "agent_definition": AGENT,
            "tasks": [AgentNodeTaskData(name="task_a", order=0, instructions="Write.")],
            **data,
        }
    )
    return AgentNode(
        session_id=SESSION_ID,
        node_name="agent_node_1",
        stop_event=StopEvent(),
        agent_node_data=node_data,
        agent_task_service=service,
        storage_credentials=storage_credentials,
    )


NODE_KINDS = pytest.mark.parametrize(
    ("build_node", "stream_type"),
    [(_task_node, "task_node_stream"), (_agent_node, "agent_node_stream")],
    ids=["task-node", "agent-node"],
)


async def _run(node, variables=None):
    state = {"state_history": [], "variables": DotDict(variables or {}), "system_variables": {}}
    messages = []
    await node.run(state=state, writer=messages.append)
    return state, [message.message_data for message in messages]


def _finish_output(messages):
    (finish,) = [message for message in messages if getattr(message, "message_type", None) == "finish"]
    return finish.output


@NODE_KINDS
async def test_agent_events_are_forwarded_to_the_session_stream(
    build_node, stream_type, remembered_outputs
):
    knowledge_payload = {"collection_id": 7, "rag_id": 3, "chunks": [{"text": "chunk"}]}
    service = FakeAgentService(
        events=[
            ("agent.task_start", {"task": {"name": "task_a", "order": 0}}),
            ("agent.tool_call", {"id": "call_1", "name": "search", "arguments": "{}"}),
            ("agent.knowledge_search", knowledge_payload),
            ("agent.heartbeat", {}),
            ("agent.tool_result", {"tool_call_id": "call_1", "content": "result"}),
            ("agent.task_finish", {"task": {"name": "task_a", "order": 0}, "message": "done"}),
        ]
    )

    _, messages = await _run(build_node(service, remembered_outputs))

    forwarded = [
        message for message in messages
        if isinstance(message, dict)
        and message.get("message_type") in (stream_type, "extracted_chunks")
    ]
    assert forwarded == [
        {"message_type": stream_type, "event": "task_start", "step_id": 1, "is_final": False,
         "agent_id": 1, "data": {"task": {"name": "task_a", "order": 0}}},
        {"message_type": stream_type, "event": "tool_call", "step_id": 2, "is_final": False,
         "agent_id": 1, "data": {"id": "call_1", "name": "search", "arguments": "{}"}},
        # Retrieved chunks are their own message and do not take a step number.
        {"message_type": "extracted_chunks", "agent_id": 1, **knowledge_payload},
        {"message_type": stream_type, "event": "tool_result", "step_id": 3, "is_final": False,
         "agent_id": 1, "data": {"tool_call_id": "call_1", "content": "result"}},
        {"message_type": stream_type, "event": "task_finish", "step_id": 4, "is_final": False,
         "agent_id": 1, "data": {"task": {"name": "task_a", "order": 0}, "message": "done"}},
    ]


def _skipped_notices(messages):
    return [
        message for message in messages
        if isinstance(message, dict) and message.get("event") == "llm_fallback_skipped"
    ]


@NODE_KINDS
async def test_skipped_fallback_is_reported_once_when_the_node_starts(
    build_node, stream_type, remembered_outputs
):
    agent = AGENT.model_copy(update={"fallback_llm_warning": "Fallback LLM was skipped: no API key."})
    service = FakeAgentService(events=[("agent.task_start", {"task": {"name": "task_a", "order": 0}})])

    _, messages = await _run(build_node(service, remembered_outputs, agent_definition=agent))

    stream = [message for message in messages if isinstance(message, dict) and "event" in message]
    assert [(message["event"], message["step_id"]) for message in stream] == [
        ("llm_fallback_skipped", 1),
        ("task_start", 2),
    ]
    assert _skipped_notices(messages) == [
        {"message_type": stream_type, "event": "llm_fallback_skipped", "step_id": 1,
         "is_final": False, "agent_id": 1, "data": {"message": "Fallback LLM was skipped: no API key."}},
    ]


@NODE_KINDS
async def test_no_skipped_notice_without_a_warning(build_node, stream_type, remembered_outputs):
    _, messages = await _run(build_node(FakeAgentService(), remembered_outputs))

    assert _skipped_notices(messages) == []


@NODE_KINDS
@pytest.mark.parametrize(
    ("result", "expected_variable"),
    [
        ({"final_text": "The summary."}, "The summary."),
        ({"final_text": '{"a": {"b": 1}}', "structured_output": {"a": {"b": 1}}}, {"a": {"b": 1}}),
        # A non-object root schema yields a list, not the raw JSON text.
        ({"final_text": '["one", "two"]', "structured_output": ["one", "two"]}, ["one", "two"]),
    ],
    ids=["text", "structured-object", "structured-list"],
)
async def test_result_is_stored_at_the_output_variable_path(
    build_node, stream_type, remembered_outputs, result, expected_variable
):
    node = build_node(
        FakeAgentService(result=result), remembered_outputs, output_variable_path="variables.output"
    )

    state, _ = await _run(node)

    assert state["variables"].output == expected_variable
    if isinstance(expected_variable, dict):
        # Downstream nodes read it with attribute access (variables.output.a.b).
        assert state["variables"].output.a.b == 1


@NODE_KINDS
@pytest.mark.parametrize(
    ("agent_definition", "error"),
    [(None, "agent_definition"), (AgentDefinitionData(id=1, name="researcher"), "llm")],
    ids=["no-agent", "agent-without-llm"],
)
async def test_misconfigured_node_fails_without_calling_the_agent(
    build_node, stream_type, remembered_outputs, agent_definition, error
):
    service = FakeAgentService()
    node = build_node(service, remembered_outputs, agent_definition=agent_definition)

    with pytest.raises(ValueError, match=error):
        await _run(node)

    assert service.dispatched is None


@NODE_KINDS
async def test_agent_failure_propagates(build_node, stream_type, remembered_outputs):
    node = build_node(FakeAgentService(error=RuntimeError("agent unreachable")), remembered_outputs)

    with pytest.raises(RuntimeError, match="agent unreachable"):
        await _run(node)


@NODE_KINDS
async def test_storage_credentials_reach_the_agent(build_node, stream_type, remembered_outputs):
    service = FakeAgentService()
    credentials = StorageCredentials(access_key="scoped-ak", secret_key="scoped-sk")

    await _run(build_node(service, remembered_outputs, storage_credentials=credentials))

    assert service.storage_credentials == credentials


# --- TaskNode ---------------------------------------------------------------


async def test_task_node_returns_the_agent_run_summary(remembered_outputs):
    service = FakeAgentService(
        result={
            "final_text": "The summary.",
            "token_usage": {"total_tokens": 42},
            "stop_reason": "completed",
            "iterations": 3,
            "tool_invocations": 1,
        }
    )

    _, messages = await _run(_task_node(service, remembered_outputs))

    assert _finish_output(messages) == {
        "message": "The summary.",
        "structured_output": None,
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
    }


@pytest.mark.parametrize(
    ("instructions", "variables", "expected"),
    [
        ("Write about {topic}", {"topic": "cats"}, "Write about cats"),
        ("Write about {missing}", {}, "Write about {missing}"),
        ('Return JSON like {"a": 1}', {}, 'Return JSON like {"a": 1}'),
        ("Write {{topic}} about {topic}", {"topic": "cats"}, "Write {topic} about cats"),
        ("Write about {topic.upper}", {"topic": "cats"}, "Write about {topic.upper}"),
        ("Write about {topic[0]}", {"topic": "cats"}, "Write about {topic[0]}"),
        ("Answer {context[user_input]}", {"context": {"user_input": "hi"}}, "Answer hi"),
        ("Answer {context.user_input}", {"context": {"user_input": "hi"}}, "Answer hi"),
    ],
    ids=[
        "placeholder",
        "unknown-placeholder-kept",
        "json-example-verbatim",
        "escaped-braces",
        "attribute-of-text-left-as-written",
        "index-into-text-left-as-written",
        "key-path",
        "dotted-key-path",
    ],
)
async def test_task_instructions_are_rendered_from_the_input(
    remembered_outputs, instructions, variables, expected
):
    service = FakeAgentService()
    node = _task_node(
        service,
        remembered_outputs,
        instructions=instructions,
        input_map={"topic": "variables.topic", "context": "variables.context"},
    )

    await _run(node, variables)

    assert service.dispatched.instructions == expected


@pytest.fixture
def warnings_logged():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="WARNING", format="{message}")
    yield lines
    logger.remove(sink_id)


@pytest.mark.parametrize(
    ("instructions", "expected_warnings"),
    [
        ("Write about {topic}", []),
        (
            "Greet {0} about {topic}",
            [
                "Instructions sent as written, no placeholder filled: "
                "Placeholder '{0}' has no variable name, so it is never filled."
            ],
        ),
        (
            "Write {missing} about {topic}, then {user.name} and {missing}",
            [
                "Instructions: no input value for placeholder {missing}; left as-is",
                "Instructions: no input value for placeholder {user.name}; left as-is",
            ],
        ),
    ],
    ids=["rendered-no-warning", "unrendered-template-explains-why", "each-missing-placeholder-once"],
)
async def test_task_instructions_not_fully_rendered_leave_a_warning(
    remembered_outputs, warnings_logged, instructions, expected_warnings
):
    node = _task_node(
        FakeAgentService(),
        remembered_outputs,
        instructions=instructions,
        input_map={"topic": "variables.topic"},
    )

    await _run(node, {"topic": "cats"})

    assert [line.strip() for line in warnings_logged if "Instructions" in line] == expected_warnings


def _task_node_with_instructions(service, store, instructions, input_map):
    return _task_node(service, store, instructions=instructions, input_map=input_map)


def _agent_node_with_instructions(service, store, instructions, input_map):
    tasks = [AgentNodeTaskData(name="task_a", order=0, instructions=instructions)]
    return _agent_node(service, store, tasks=tasks, input_map=input_map)


@pytest.mark.parametrize(
    "build_node",
    [_task_node_with_instructions, _agent_node_with_instructions],
    ids=["task-node", "agent-node"],
)
async def test_input_mapped_to_a_method_fails_before_the_agent_is_called(
    build_node, remembered_outputs
):
    service = FakeAgentService()
    node = build_node(
        service,
        remembered_outputs,
        instructions="{fn.__globals__[ast].sys.modules[os].environ[REDIS_PASSWORD]}",
        input_map={"fn": "variables.update"},
    )

    with pytest.raises(InvalidStatePathError, match="'variables.update'"):
        await _run(node)

    assert service.dispatched is None


@pytest.mark.parametrize(
    "build_node",
    [_task_node_with_instructions, _agent_node_with_instructions],
    ids=["task-node", "agent-node"],
)
async def test_refused_placeholder_fails_the_node_with_its_own_message_before_the_agent_is_called(
    build_node, remembered_outputs
):
    service = FakeAgentService()
    node = build_node(
        service,
        remembered_outputs,
        instructions="Answer {context._x}",
        input_map={"context": "variables.context"},
    )
    state = {
        "state_history": [],
        "variables": DotDict({"context": {"_x": "hidden value"}}),
        "system_variables": {},
    }
    messages = []

    with pytest.raises(RefusedPlaceholderError) as raised:
        await node.run(state=state, writer=messages.append)

    assert service.dispatched is None
    error_details = [
        message.message_data.details
        for message in messages
        if getattr(message.message_data, "message_type", None) == "error"
    ]
    assert error_details == [str(raised.value)]
    assert "hidden value" not in error_details[0]


async def test_task_instructions_are_rendered_afresh_on_every_run(remembered_outputs):
    """A node re-entered in a cyclic flow must not reuse the first run's rendering."""
    service = FakeAgentService()
    node = _task_node(
        service, remembered_outputs, instructions="Write about {topic}",
        input_map={"topic": "variables.topic"},
    )

    await _run(node, {"topic": "cats"})
    await _run(node, {"topic": "dogs"})

    assert service.dispatched.instructions == "Write about dogs"


@pytest.mark.parametrize(
    ("remember_output", "final_text", "remembered"),
    [
        (True, "The summary.", [("task_node_1", "The summary.")]),
        (False, "The summary.", []),
        (True, "", []),
    ],
    ids=["remembered", "remember-off", "empty-output-not-remembered"],
)
async def test_task_output_is_remembered_for_later_tasks_only_when_asked(
    remembered_outputs, remember_output, final_text, remembered
):
    node = _task_node(
        FakeAgentService(result={"final_text": final_text}),
        remembered_outputs,
        remember_output=remember_output,
    )

    await _run(node)

    assert await remembered_outputs.fetch_all(SESSION_ID) == remembered


async def test_remembered_outputs_are_prepended_to_the_next_tasks_instructions(remembered_outputs):
    await remembered_outputs.store(SESSION_ID, "earlier_task", "earlier output")
    service = FakeAgentService()

    await _run(_task_node(service, remembered_outputs, instructions="Summarize."))

    fenced_block_then_instructions = re.compile(
        r"===== PREVIOUS TASKS OUTPUTS (?P<nonce>[0-9a-f]{16}) =====\n"
        r".*Task 'earlier_task':\nearlier output\n"
        r".*===== END PREVIOUS TASKS OUTPUTS (?P=nonce) =====\n+"
        r"Summarize\.",
        re.DOTALL,
    )
    assert fenced_block_then_instructions.fullmatch(service.dispatched.instructions)


# --- AgentNode --------------------------------------------------------------


@pytest.mark.parametrize(
    ("tasks", "expected_tasks"),
    [
        (
            [{"name": "task_a", "order": 0, "final_text": "A done", "token_usage": {"total_tokens": 10},
              "iterations": 2, "tool_invocations": 1, "stop_reason": "completed"}],
            [{"name": "task_a", "order": 0, "message": "A done", "structured_output": None,
              "token_usage": {"total_tokens": 10}, "iterations": 2, "tool_invocations": 1}],
        ),
        # An agent service that predates per-task results sends no "tasks" key.
        (None, []),
    ],
    ids=["per-task-results", "no-per-task-results"],
)
async def test_agent_node_returns_the_run_summary_with_each_task(
    remembered_outputs, tasks, expected_tasks
):
    result = {"final_text": "The summary.", "token_usage": {"total_tokens": 42},
              "stop_reason": "completed", "iterations": 3, "tool_invocations": 1}
    if tasks is not None:
        result["tasks"] = tasks

    _, messages = await _run(_agent_node(FakeAgentService(result=result), remembered_outputs))

    assert _finish_output(messages) == {
        "message": "The summary.",
        "structured_output": None,
        "token_usage": {"total_tokens": 42},
        "stop_reason": "completed",
        "iterations": 3,
        "tool_invocations": 1,
        "tasks": expected_tasks,
    }


async def test_agent_node_renders_every_tasks_instructions(remembered_outputs):
    service = FakeAgentService()
    node = _agent_node(
        service,
        remembered_outputs,
        tasks=[
            AgentNodeTaskData(name="task_a", order=0, instructions="Write about {topic}"),
            AgentNodeTaskData(
                name="task_b", order=1, instructions="Summarize {topic} findings",
                context_tasks=["task_a"],
            ),
        ],
        input_map={"topic": "variables.topic"},
    )

    await _run(node, {"topic": "cats"})

    assert [task.instructions for task in service.dispatched.tasks] == [
        "Write about cats",
        "Summarize cats findings",
    ]


async def test_agent_node_without_tasks_fails_without_calling_the_agent(remembered_outputs):
    service = FakeAgentService()

    with pytest.raises(ValueError, match="no tasks"):
        await _run(_agent_node(service, remembered_outputs, tasks=[]))

    assert service.dispatched is None
