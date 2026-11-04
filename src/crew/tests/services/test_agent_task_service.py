"""AgentTaskService: crew's adapter to the agent microservice over Redis Streams.

A run publishes `agent.run` on the request stream with the request blob under a
Redis key, then reads only its own result stream `<prefix>:<correlation_id>`
until a result, an error, a timeout or a stop. A fake agent below plays the
other side of that contract.

The Redis double is an in-process fake rather than fakeredis: fakeredis's async
blocking XREAD was verified (via isolated repro scripts) to block the whole event
loop until its own block timeout elapses, so the fake agent task would never get
scheduled. FakeStreamClient yields control on every call instead.
"""

import asyncio
import json
import types

import pytest

from loguru import logger

from services import agent_run_errors
from services.agent_run_errors import AgentTaskError, AgentTaskTimeoutError
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.exceptions import StopSession
from src.shared.models import (
    AgentDefinitionData,
    AgentNodeData,
    AgentNodeTaskData,
    LLMConfigData,
    LLMData,
    TaskNodeData,
)
from src.shared.models.agent_service import AgentRequest
from src.shared.models.storage_scope import StorageCredentials
from src.shared.models.surfaces import CombinedSurfaceData
from src.shared.redis_streams import StreamEnvelope, agent_result_stream

pytestmark = pytest.mark.asyncio

LLM = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o"))
COMPLETED = ("agent.result", {"final_text": "done", "stop_reason": "completed"})


class FakeStreamClient:
    """In-memory, cooperative stand-in for the aioredis calls the service makes
    (set/get/delete/xadd/xread). Records every stream read and its block time."""

    def __init__(self):
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.keys: dict[str, str] = {}
        self._next_message_id = 1
        self.reads: list[tuple[str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None):
        self.keys[key] = value

    async def get(self, key: str) -> str | None:
        return self.keys.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self.keys.pop(key, None)
            self.streams.pop(key, None)

    async def xadd(self, stream: str, fields: dict, **options) -> str:
        message_id = str(self._next_message_id)
        self._next_message_id += 1
        self.streams.setdefault(stream, []).append((message_id, fields))
        await asyncio.sleep(0)
        return message_id

    async def xread(self, streams: dict, block: int | None = None, count: int | None = None):
        await asyncio.sleep(0)
        response = []
        for name, after_id in streams.items():
            self.reads.append((name, block))
            new_entries = [
                (message_id, fields)
                for message_id, fields in self.streams.get(name, [])
                if int(message_id) > int(after_id)
            ]
            if new_entries:
                response.append([name, new_entries[:count] if count else new_entries])
        if response:
            return response
        if block:
            await asyncio.sleep(min(block / 1000, 0.02))
        return []


@pytest.fixture
def client():
    return FakeStreamClient()


@pytest.fixture
def service(client):
    return AgentTaskService(redis_service=types.SimpleNamespace(aioredis_client=client), poll_block_ms=50)


def _task_node(name="task_node_1", **agent_fields) -> TaskNodeData:
    return TaskNodeData(
        node_name=name,
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research the topic.", **{"llm": LLM, **agent_fields}
        ),
        instructions=f"instructions for {name}",
    )


def _start_task(service, node: TaskNodeData, stop_event: StopEvent, **kwargs):
    """Start a run the way TaskNode does, passing the agent and LLM it has checked."""
    return service.run_task(
        node, stop_event, agent_definition=node.agent_definition, llm=node.agent_definition.llm, **kwargs
    )


def _start_agent_node(service, node: AgentNodeData, stop_event: StopEvent, **kwargs):
    """Start a run the way AgentNode does, passing the agent and LLM it has checked."""
    return service.run_agent_node(
        node, stop_event, agent_definition=node.agent_definition, llm=node.agent_definition.llm, **kwargs
    )


class FakeAgent:
    """Answers the next request with `replies`, keeping the request blob it received."""

    def __init__(self, client: FakeStreamClient, service: AgentTaskService, replies=(COMPLETED,)):
        self.client = client
        self.service = service
        self.replies = replies
        self.request: dict | None = None

    async def reply_to(self, correlation_id: str, replies) -> None:
        for event_type, payload in replies:
            envelope = StreamEnvelope(type=event_type, correlation_id=correlation_id, payload=payload)
            await self.client.xadd(
                agent_result_stream(self.service.result_stream_prefix, correlation_id),
                envelope.to_fields(),
            )

    async def __call__(self) -> None:
        while not (response := await self.client.xread({self.service.request_stream: "0"}, block=100, count=1)):
            pass
        (_, [(_, fields)]) = response[0]
        request = StreamEnvelope.from_fields(fields)
        self.request = json.loads(await self.client.get(request.payload["request_key"]))
        await self.reply_to(request.correlation_id, self.replies)


async def _run(service, client, run=None, replies=(COMPLETED,), **kwargs):
    """Run a task against a fake agent; returns (result or raised error, the agent)."""
    agent = FakeAgent(client, service, replies)
    responder = asyncio.create_task(agent())
    try:
        result = await (run or (lambda: _start_task(service, _task_node(), StopEvent(), **kwargs)))()
    except Exception as error:
        result = error
    finally:
        responder.cancel()
    return result, agent


def _leftover_run_keys(client, service) -> list[str]:
    """Request keys and per-run result streams; a finished run must leave none."""
    prefix = f"{service.result_stream_prefix}:"
    return list(client.keys) + [name for name in client.streams if name.startswith(prefix)]


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (COMPLETED, {"final_text": "done", "stop_reason": "completed"}),
        # Hitting the failure limit still produced a summary the flow can use.
        (
            ("agent.result", {"stop_reason": "max_consecutive_failures", "final_text": "summary"}),
            {"stop_reason": "max_consecutive_failures", "final_text": "summary"},
        ),
    ],
    ids=["completed", "max-consecutive-failures"],
)
async def test_run_ends_with_the_agents_answer_and_leaves_no_keys(service, client, reply, expected):
    result, _ = await _run(service, client, replies=[reply])

    assert result == expected
    assert _leftover_run_keys(client, service) == []


REFERENCE = "0a1b2c3d4e5f"
PROVIDER_SECRET = "sk-proj-abc1****wxyz"
RAW_PROVIDER_TEXT = (
    "litellm.AuthenticationError: AuthenticationError: OpenAIException - "
    f"Incorrect API key provided: {PROVIDER_SECRET}"
)
LLM_FAILURE_TEXTS = {
    "authentication": (
        'The provider rejected the API key for model "gpt-4o". Check the key in the LLM settings.'
    ),
    "rate_limit": (
        "The provider's rate limit for model \"gpt-4o\" was reached. Wait a minute and run the "
        "flow again, or lower the agent's requests per minute."
    ),
    "quota_exceeded": (
        'The provider account for model "gpt-4o" has run out of credit. Top it up, or choose '
        "another LLM."
    ),
    "context_too_long": (
        'The prompt is too long for model "gpt-4o". Shorten the task or its inputs, or choose a '
        "model with a bigger context window."
    ),
    "model_not_found": (
        'The provider has no model "gpt-4o". Check the model name in the LLM settings.'
    ),
    "provider_unavailable": (
        "The provider of model \"gpt-4o\" isn't responding. Try again in a few minutes."
    ),
    "content_refused": (
        'The provider of model "gpt-4o" refused the request because of its content policy. '
        "Change the task or its inputs."
    ),
    "provider_timeout": 'The provider of model "gpt-4o" took too long to answer. Try again.',
}
UNKNOWN_LLM_FAILURE_TEXT = (
    'The LLM request for model "gpt-4o" failed. '
    f"Try again or contact your administrator (reference: {REFERENCE})."
)
AGENT_SERVICE_NO_ANSWER_TEXT = (
    "The agent service didn't answer in time. "
    f"Try again or contact your administrator (reference: {REFERENCE})."
)


@pytest.fixture
def fixed_reference(monkeypatch):
    monkeypatch.setattr(agent_run_errors, "new_error_correlation_id", lambda: REFERENCE)


@pytest.fixture
def warning_logs():
    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING")
    yield records
    logger.remove(sink_id)


def _llm_failure(envelope_type: str, error_kind: str | None) -> tuple[str, dict]:
    payload = {"stop_reason": "llm_error", "error": RAW_PROVIDER_TEXT}
    if error_kind is not None:
        payload["error_kind"] = error_kind
    return envelope_type, payload


ENVELOPE_TYPES = pytest.mark.parametrize("envelope_type", ["agent.result", "agent.error"])


@ENVELOPE_TYPES
@pytest.mark.parametrize(("error_kind", "expected_text"), LLM_FAILURE_TEXTS.items())
async def test_llm_failure_shows_what_the_user_can_do_and_logs_only_its_kind(
    service, client, warning_logs, envelope_type, error_kind, expected_text
):
    result, _ = await _run(service, client, replies=[_llm_failure(envelope_type, error_kind)])

    assert isinstance(result, AgentTaskError)
    assert str(result) == expected_text
    assert result.correlation_id is None
    assert _leftover_run_keys(client, service) == []
    [logged] = [record for record in warning_logs if "Agent run failed" in record]
    assert f"Agent run failed: {error_kind} (agent_correlation_id=" in logged
    assert PROVIDER_SECRET not in "".join(warning_logs)


async def test_missing_model_at_a_custom_base_url_points_at_the_url_too(service, client):
    llm = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o", base_url="https://llm.example.com/v1"))

    result, _ = await _run(
        service, client, replies=[_llm_failure("agent.result", "model_not_found")],
        run=lambda: _start_task(service, _task_node(llm=llm), StopEvent()),
    )

    assert str(result) == (
        'The provider has no model "gpt-4o". Check the model name and base URL in the LLM settings.'
    )


@ENVELOPE_TYPES
@pytest.mark.parametrize(
    "error_kind", ["unknown", None, "kind_from_a_newer_agent"], ids=["unknown", "missing", "unrecognized"]
)
async def test_unexplained_llm_failure_cites_a_reference_logged_with_the_error_class_only(
    service, client, fixed_reference, warning_logs, envelope_type, error_kind
):
    result, _ = await _run(service, client, replies=[_llm_failure(envelope_type, error_kind)])

    assert str(result) == UNKNOWN_LLM_FAILURE_TEXT
    assert result.correlation_id == REFERENCE
    [logged] = [record for record in warning_logs if REFERENCE in record]
    assert f"litellm.AuthenticationError: <redacted len={len(RAW_PROVIDER_TEXT)}>" in logged
    assert PROVIDER_SECRET not in "".join(warning_logs)


@pytest.mark.parametrize(
    "reply",
    [
        ("agent.error", {"error": "output did not satisfy schema after 2 retries"}),
        ("agent.result", {"stop_reason": "internal_error", "error": "Redis connection lost"}),
        ("agent.error", {"stop_reason": "internal_error", "error": "Redis connection lost"}),
    ],
    ids=["no-stop-reason", "internal-error-result", "internal-error-error"],
)
async def test_agent_failure_outside_the_llm_call_gets_the_generic_message(
    service, client, fixed_reference, warning_logs, reply
):
    result, _ = await _run(service, client, replies=[reply])

    assert str(result) == f"Node execution failed (reference: {REFERENCE})"
    assert result.correlation_id == REFERENCE
    [logged] = [record for record in warning_logs if REFERENCE in record]
    assert f"<unknown class>: <redacted len={len(reply[1]['error'])}>" in logged
    assert reply[1]["error"] not in "".join(warning_logs)


@ENVELOPE_TYPES
@pytest.mark.parametrize(
    ("max_execution_time", "expected_limit"),
    [(60, "60 seconds"), (1, "1 second"), (1_000_000, "1000000 seconds")],
    ids=["seconds", "one-second", "large-limit"],
)
async def test_agent_time_limit_names_the_agent_and_its_limit(
    service, client, envelope_type, max_execution_time, expected_limit
):
    timeout = (envelope_type, {"stop_reason": "timeout", "error": f"execution exceeded {max_execution_time}s"})

    result, _ = await _run(
        service, client, replies=[timeout],
        run=lambda: _start_task(service, _task_node(max_execution_time=max_execution_time), StopEvent()),
    )

    assert isinstance(result, AgentTaskTimeoutError)
    assert str(result) == (
        f"Agent \"researcher\" didn't finish within {expected_limit}. "
        "Raise its max execution time, or make the task simpler."
    )
    assert result.correlation_id is None


@ENVELOPE_TYPES
async def test_agent_reported_timeout_without_a_limit_gets_the_generic_message(
    service, client, fixed_reference, envelope_type
):
    timeout = (envelope_type, {"stop_reason": "timeout", "error": "execution exceeded Nones"})

    result, _ = await _run(
        service, client, replies=[timeout],
        run=lambda: _start_task(service, _task_node(max_execution_time=None), StopEvent()),
    )

    assert str(result) == f"Node execution failed (reference: {REFERENCE})"
    assert result.correlation_id == REFERENCE


async def test_live_events_reach_on_event_in_order_and_others_are_skipped(service, client):
    collected: list[str] = []
    events = [
        ("agent.task_start", {"task": {"name": "task_a", "order": 0}}),
        ("agent.tool_call", {"id": "call_1", "name": "search", "arguments": "{}"}),
        ("agent.heartbeat", {}),
        ("agent.knowledge_search", {"collection_id": 7, "chunks": []}),
        ("agent.tool_result", {"tool_call_id": "call_1", "content": "result"}),
        ("agent.task_finish", {"task": {"name": "task_a", "order": 0}, "message": "done"}),
    ]

    result, _ = await _run(
        service, client, replies=[*events, COMPLETED],
        on_event=lambda envelope: collected.append(envelope.type),
    )

    assert collected == [
        "agent.task_start", "agent.tool_call", "agent.knowledge_search",
        "agent.tool_result", "agent.task_finish",
    ]
    assert result["final_text"] == "done"


@pytest.mark.parametrize(
    "on_event",
    [None, lambda envelope: (_ for _ in ()).throw(RuntimeError("callback exploded"))],
    ids=["no-callback", "callback-raises"],
)
async def test_live_events_never_break_the_run(service, client, on_event):
    tool_call = ("agent.tool_call", {"id": "call_1", "name": "search", "arguments": "{}"})

    result, _ = await _run(service, client, replies=[tool_call, COMPLETED], on_event=on_event)

    assert result["final_text"] == "done"


async def test_run_never_reads_another_runs_result_stream(service, client):
    """Another run's stream may hold another org's answer."""
    collected: list[StreamEnvelope] = []
    agent = FakeAgent(client, service, replies=[])
    foreign_stream = agent_result_stream(service.result_stream_prefix, "foreign-run")

    async def agent_that_also_answers_another_run():
        await agent()
        await agent.reply_to("foreign-run", [
            ("agent.tool_call", {"id": "call_x", "name": "leak", "arguments": "{}"}),
            ("agent.result", {"final_text": "another org's answer", "stop_reason": "completed"}),
        ])
        own_request_key = next(iter(client.keys))
        await agent.reply_to(own_request_key.rsplit(":", 1)[1], [
            ("agent.result", {"final_text": "correct", "stop_reason": "completed"}),
        ])

    responder = asyncio.create_task(agent_that_also_answers_another_run())
    result = await _start_task(service, _task_node(), StopEvent(), on_event=collected.append)
    await responder

    assert result["final_text"] == "correct"
    assert collected == []
    assert foreign_stream not in [name for name, _ in client.reads]
    assert len(client.streams[foreign_stream]) == 2


async def test_concurrent_runs_each_receive_only_their_own_result(service, client):
    async def agent_echoing_instructions():
        answered: set[str] = set()
        while len(answered) < 2:
            for _, entries in await client.xread({service.request_stream: "0"}, block=100):
                for message_id, fields in entries:
                    if message_id in answered:
                        continue
                    answered.add(message_id)
                    request = StreamEnvelope.from_fields(fields)
                    blob = json.loads(await client.get(request.payload["request_key"]))
                    await FakeAgent(client, service).reply_to(request.correlation_id, [
                        ("agent.result", {"final_text": blob["payload"]["task_instructions"], "stop_reason": "completed"}),
                    ])

    responder = asyncio.create_task(agent_echoing_instructions())
    first, second = await asyncio.gather(
        _start_task(service, _task_node("run_a"), StopEvent()),
        _start_task(service, _task_node("run_b"), StopEvent()),
    )
    await responder

    assert (first["final_text"], second["final_text"]) == ("instructions for run_a", "instructions for run_b")
    assert _leftover_run_keys(client, service) == []


async def test_timeout_raises_after_forwarding_what_arrived_and_leaves_no_keys(client, fixed_reference):
    service = AgentTaskService(
        redis_service=types.SimpleNamespace(aioredis_client=client), default_timeout=0.2, poll_block_ms=20
    )
    collected: list[str] = []

    result, _ = await _run(
        service, client, replies=[("agent.task_start", {"task": {"name": "task_a", "order": 0}})],
        on_event=lambda envelope: collected.append(envelope.type),
    )

    assert isinstance(result, AgentTaskTimeoutError)
    assert str(result) == AGENT_SERVICE_NO_ANSWER_TEXT
    assert result.correlation_id == REFERENCE
    assert collected == ["agent.task_start"]
    assert _leftover_run_keys(client, service) == []


async def test_crew_giving_up_says_the_agent_service_didnt_answer_not_the_agents_limit(
    client, fixed_reference, warning_logs
):
    service = AgentTaskService(
        redis_service=types.SimpleNamespace(aioredis_client=client), timeout_buffer_s=0.2, poll_block_ms=20
    )

    result, _ = await _run(
        service, client, replies=[],
        run=lambda: _start_task(service, _task_node(max_execution_time=1), StopEvent()),
    )

    assert isinstance(result, AgentTaskTimeoutError)
    assert str(result) == AGENT_SERVICE_NO_ANSWER_TEXT
    assert result.correlation_id == REFERENCE
    [logged] = [record for record in warning_logs if REFERENCE in record]
    assert "didn't answer within 1.2s" in logged


async def test_stop_mid_wait_raises_stop_session_and_leaves_no_keys(service, client):
    stop_event = StopEvent()

    def stop_on_first_event(envelope):
        stop_event.set()

    result, _ = await _run(
        service, client,
        run=lambda: _start_task(service, _task_node(), stop_event, on_event=stop_on_first_event),
        replies=[("agent.task_start", {"task": {"name": "task_a", "order": 0}})],
    )

    assert isinstance(result, StopSession)
    assert _leftover_run_keys(client, service) == []


async def test_task_request_carries_the_agent_spec_and_task(service, client):
    credentials = StorageCredentials(access_key="scoped-ak", secret_key="scoped-sk")
    node = _task_node(max_tool_calls=5, tool_timeout=30, max_consecutive_failures=2, schema_max_retries=4)
    node = node.model_copy(
        update={
            "surface": CombinedSurfaceData(instructions="Never reveal secrets."),
            "output_schema": {"type": "object"},
        }
    )

    _, agent = await _run(
        service, client, run=lambda: _start_task(service, node, StopEvent(), storage_credentials=credentials)
    )

    request = AgentRequest(correlation_id="unused", **agent.request)
    assert request.run_type == "SINGLE_TASK"
    (spec,) = request.agents
    # Surface instructions are appended to the agent's own.
    assert spec.instructions == "Research the topic.\n\nNever reveal secrets."
    assert (spec.max_tool_calls, spec.tool_timeout, spec.max_consecutive_failures, spec.schema_max_retries) == (5, 30, 2, 4)
    assert request.payload == {"task_instructions": "instructions for task_node_1", "output_schema": {"type": "object"}}
    assert request.storage_credentials == credentials


@pytest.mark.parametrize(
    "fallback_llm",
    [LLMData(provider="anthropic", config=LLMConfigData(model="claude-sonnet")), None],
    ids=["with-fallback", "without-fallback"],
)
async def test_request_spec_carries_the_agents_fallback_llm(service, client, fallback_llm):
    node = _task_node(fallback_llm=fallback_llm)

    _, agent = await _run(service, client, run=lambda: service.run_task(node, StopEvent()))

    (spec,) = AgentRequest(correlation_id="unused", **agent.request).agents
    assert spec.fallback_llm == fallback_llm


async def test_fallback_envelope_is_forwarded_live(service, client):
    collected: list[str] = []
    payload = {
        "task": None,
        "primary": {"config_name": "main", "model": "gpt-4o"},
        "fallback": {"config_name": "backup", "model": "claude-sonnet"},
        "error_type": "RateLimitError",
    }

    await _run(
        service, client, replies=[("agent.llm_fallback", payload), COMPLETED],
        on_event=lambda envelope: collected.append(envelope.type),
    )

    assert collected == ["agent.llm_fallback"]


async def test_agent_node_request_lists_every_task_with_its_context(service, client):
    node = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(id=1, name="researcher", instructions="Research the topic.", llm=LLM),
        tasks=[
            AgentNodeTaskData(name="task_a", order=0, instructions="Write draft."),
            AgentNodeTaskData(
                name="task_b", order=1, instructions="Polish draft.",
                output_schema={"type": "object"}, context_tasks=["task_a"],
            ),
        ],
    )

    _, agent = await _run(service, client, run=lambda: _start_agent_node(service, node, StopEvent()))

    assert agent.request["run_type"] == "LIST_OF_TASKS"
    assert agent.request["payload"]["tasks"] == [
        {"name": "task_a", "instructions": "Write draft.", "output_schema": None, "context": []},
        {"name": "task_b", "instructions": "Polish draft.", "output_schema": {"type": "object"}, "context": ["task_a"]},
    ]


def _agent_node(task_count: int, max_execution_time: int | None) -> AgentNodeData:
    return AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research.", llm=LLM, max_execution_time=max_execution_time
        ),
        tasks=[AgentNodeTaskData(name=f"task_{index}", order=index, instructions="Do.") for index in range(task_count)],
    )


@pytest.mark.parametrize(
    ("max_execution_time", "task_count", "expected_timeout_s"),
    [
        (10, None, 10 + 60),
        (10, 3, 10 * 3 + 60),
        (None, None, 600),
        (None, 3, 600 * 3),
    ],
    ids=["task-own-limit-plus-buffer", "agent-node-scales-by-tasks", "task-default", "agent-node-default-scaled"],
)
async def test_wait_is_bounded_by_the_agents_execution_limit(client, max_execution_time, task_count, expected_timeout_s):
    # A poll block longer than any timeout makes the first wait equal to the whole timeout.
    service = AgentTaskService(
        redis_service=types.SimpleNamespace(aioredis_client=client),
        default_timeout=600.0, timeout_buffer_s=60.0, poll_block_ms=10**9,
    )
    if task_count is None:
        node = _task_node(max_execution_time=max_execution_time)
        run = lambda: _start_task(service, node, StopEvent())  # noqa: E731
    else:
        run = lambda: _start_agent_node(service, _agent_node(task_count, max_execution_time), StopEvent())  # noqa: E731

    await _run(service, client, run=run)

    first_wait_ms = next(block for name, block in client.reads if name.startswith(service.result_stream_prefix))
    assert first_wait_ms / 1000 == pytest.approx(expected_timeout_s, abs=1)
