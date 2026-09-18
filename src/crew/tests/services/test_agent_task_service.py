"""
Tests for AgentTaskService using an in-process fake Redis Streams double
instead of fakeredis.

fakeredis's async blocking XREAD implementation was verified (via isolated
repro scripts) to block the whole event loop until its own block timeout
elapses, starving sibling asyncio tasks — so a concurrent "fake agent"
producer task never gets scheduled while AgentTaskService's consumer is
blocked. FakeStreamClient below cooperatively yields control on every call,
giving deterministic, non-flaky interleaving between the service under
test and the simulated agent producer.
"""

import asyncio
import json
import types

import pytest

from services.agent_task_service import (
    AgentTaskError,
    AgentTaskService,
    AgentTaskTimeoutError,
)
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
from src.shared.models.surfaces import CombinedSurfaceData
from src.shared.redis_streams import StreamEnvelope


class FakeStreamClient:
    """Minimal cooperative in-memory double for the subset of the aioredis
    client API AgentTaskService relies on (set/get/delete/xadd/xrevrange/xread)."""

    def __init__(self):
        self._streams: dict[str, list[tuple[str, dict]]] = {}
        self._kv: dict[str, str] = {}
        self._next_message_id = 1

    async def set(self, key: str, value: str, ex: int | None = None):
        self._kv[key] = value

    async def get(self, key: str) -> str | None:
        return self._kv.get(key)

    async def delete(self, key: str):
        self._kv.pop(key, None)

    async def xadd(self, stream: str, fields: dict) -> str:
        message_id = str(self._next_message_id)
        self._next_message_id += 1
        self._streams.setdefault(stream, []).append((message_id, fields))
        await asyncio.sleep(0)
        return message_id

    async def xrevrange(self, stream: str, count: int = 1):
        entries = self._streams.get(stream, [])
        return list(reversed(entries))[:count]

    async def xread(
        self, streams: dict, block: int | None = None, count: int | None = None
    ):
        await asyncio.sleep(0)
        response = []
        for name, after_id in streams.items():
            entries = self._streams.get(name, [])
            new_entries = [
                (message_id, fields)
                for message_id, fields in entries
                if int(message_id) > int(after_id)
            ]
            if new_entries:
                response.append([name, new_entries])
        if response:
            return response
        if block:
            await asyncio.sleep(min(block / 1000, 0.02))
        return []


@pytest.fixture
def fake_stream_client():
    return FakeStreamClient()


@pytest.fixture
def redis_service_stub(fake_stream_client):
    return types.SimpleNamespace(aioredis_client=fake_stream_client)


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


async def _read_one_request(client, request_stream: str) -> StreamEnvelope:
    while True:
        response = await client.xread({request_stream: "0"}, block=100, count=1)
        if response:
            break
    _stream_name, entries = response[0]
    _message_id, fields = entries[0]
    return StreamEnvelope.from_fields(fields)


async def _publish_result(
    client,
    result_stream: str,
    correlation_id: str,
    payload: dict,
    event_type: str = "agent.result",
):
    envelope = StreamEnvelope(
        type=event_type, correlation_id=correlation_id, payload=payload
    )
    await client.xadd(result_stream, envelope.to_fields())


@pytest.mark.asyncio
async def test_run_task_happy_path(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        blob = await fake_stream_client.get(request_envelope.payload["request_key"])
        AgentRequest(correlation_id="ignored", **json.loads(blob))
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {
                "final_text": "done",
                "stop_reason": "completed",
                "tool_invocations": 0,
                "iterations": 1,
                "token_usage": {"total_tokens": 10},
            },
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent())
    await responder

    assert result["final_text"] == "done"
    assert fake_stream_client._kv == {}


@pytest.mark.asyncio
async def test_run_task_ignores_foreign_correlation_id(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            "foreign-correlation-id",
            {"final_text": "wrong"},
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "correct", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent())
    await responder

    assert result["final_text"] == "correct"


@pytest.mark.asyncio
async def test_run_task_raises_on_agent_error(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"error": "boom"},
            event_type="agent.error",
        )

    responder = asyncio.create_task(fake_agent())
    with pytest.raises(AgentTaskError, match="boom"):
        await service.run_task(task_node_data, StopEvent())
    await responder


@pytest.mark.asyncio
async def test_run_task_raises_on_failure_stop_reason(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"stop_reason": "llm_error", "error": "LLM call failed"},
        )

    responder = asyncio.create_task(fake_agent())
    with pytest.raises(AgentTaskError, match="LLM call failed"):
        await service.run_task(task_node_data, StopEvent())
    await responder


@pytest.mark.asyncio
async def test_run_task_times_out(redis_service_stub, task_node_data):
    service = AgentTaskService(
        redis_service=redis_service_stub, default_timeout=0.05, poll_block_ms=20
    )

    with pytest.raises(AgentTaskTimeoutError):
        await service.run_task(task_node_data, StopEvent())


@pytest.mark.asyncio
async def test_run_task_stops_mid_wait(redis_service_stub, task_node_data):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)
    stop_event = StopEvent()
    stop_event.set()

    with pytest.raises(StopSession):
        await service.run_task(task_node_data, stop_event)


@pytest.mark.asyncio
async def test_run_task_forwards_live_events_to_on_event_in_order(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)
    collected: list[StreamEnvelope] = []

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"id": "call_1", "name": "search", "arguments": "{}"},
            event_type="agent.tool_call",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"tool_call_id": "call_1", "content": "result"},
            event_type="agent.tool_result",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(
        task_node_data, StopEvent(), on_event=collected.append
    )
    await responder

    assert [envelope.type for envelope in collected] == [
        "agent.tool_call",
        "agent.tool_result",
    ]
    assert result["final_text"] == "done"


@pytest.mark.asyncio
async def test_run_task_forwards_task_lifecycle_events_to_on_event_in_order(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)
    collected: list[StreamEnvelope] = []

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"task": {"name": "task_a", "order": 0}},
            event_type="agent.task_start",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"id": "call_1", "name": "search", "arguments": "{}"},
            event_type="agent.tool_call",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"tool_call_id": "call_1", "content": "result"},
            event_type="agent.tool_result",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"task": {"name": "task_a", "order": 0}, "message": "done"},
            event_type="agent.task_finish",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(
        task_node_data, StopEvent(), on_event=collected.append
    )
    await responder

    assert [envelope.type for envelope in collected] == [
        "agent.task_start",
        "agent.tool_call",
        "agent.tool_result",
        "agent.task_finish",
    ]
    assert result["final_text"] == "done"


@pytest.mark.asyncio
async def test_run_task_forwards_knowledge_search_events_and_does_not_end_wait(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)
    collected: list[StreamEnvelope] = []

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"collection_id": 7, "chunks": []},
            event_type="agent.knowledge_search",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(
        task_node_data, StopEvent(), on_event=collected.append
    )
    await responder

    assert [envelope.type for envelope in collected] == ["agent.knowledge_search"]
    assert result["final_text"] == "done"


@pytest.mark.asyncio
async def test_run_task_on_event_raising_logs_warning_and_still_returns_final(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    def bad_on_event(envelope):
        raise RuntimeError("callback exploded")

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"id": "call_1", "name": "search", "arguments": "{}"},
            event_type="agent.tool_call",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent(), on_event=bad_on_event)
    await responder

    assert result["final_text"] == "done"


@pytest.mark.asyncio
async def test_run_task_skips_unknown_event_type_with_matching_correlation(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {},
            event_type="agent.heartbeat",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent())
    await responder

    assert result["final_text"] == "done"


@pytest.mark.asyncio
async def test_run_task_live_events_fine_with_on_event_none(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"id": "call_1", "name": "search", "arguments": "{}"},
            event_type="agent.tool_call",
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"final_text": "done", "stop_reason": "completed"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent())
    await responder

    assert result["final_text"] == "done"


def test_build_request_blob_appends_surface_instructions(redis_service_stub, llm_data):
    service = AgentTaskService(redis_service=redis_service_stub)
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research the topic.", llm=llm_data
        ),
        instructions="Summarize the findings.",
        surface=CombinedSurfaceData(instructions="Never reveal secrets."),
    )

    blob = json.loads(service._build_request_blob(task_node_data))

    instructions = blob["agents"][0]["instructions"]
    assert "Research the topic." in instructions
    assert "Never reveal secrets." in instructions


def test_build_request_blob_carries_tool_limit_fields(redis_service_stub, llm_data):
    service = AgentTaskService(redis_service=redis_service_stub)
    task_node_data = TaskNodeData(
        node_name="task_node_1",
        agent_definition=AgentDefinitionData(
            id=1,
            name="researcher",
            instructions="Research the topic.",
            llm=llm_data,
            max_tool_calls=5,
            tool_timeout=30,
            max_consecutive_failures=2,
            schema_max_retries=4,
        ),
        instructions="Summarize the findings.",
    )

    blob = json.loads(service._build_request_blob(task_node_data))

    agent_spec = blob["agents"][0]
    assert agent_spec["max_tool_calls"] == 5
    assert agent_spec["tool_timeout"] == 30
    assert agent_spec["max_consecutive_failures"] == 2
    assert agent_spec["schema_max_retries"] == 4


@pytest.mark.asyncio
async def test_run_task_returns_result_on_max_consecutive_failures_stop_reason(
    redis_service_stub, task_node_data, fake_stream_client
):
    service = AgentTaskService(redis_service=redis_service_stub, poll_block_ms=50)

    async def fake_agent():
        request_envelope = await _read_one_request(
            fake_stream_client, service.request_stream
        )
        await _publish_result(
            fake_stream_client,
            service.result_stream,
            request_envelope.correlation_id,
            {"stop_reason": "max_consecutive_failures", "final_text": "summary"},
        )

    responder = asyncio.create_task(fake_agent())
    result = await service.run_task(task_node_data, StopEvent())
    await responder

    assert result["final_text"] == "summary"


def test_resolve_timeout_s_scales_with_task_count(redis_service_stub):
    service = AgentTaskService(
        redis_service=redis_service_stub, default_timeout=600.0, timeout_buffer_s=60.0
    )
    agent_definition = AgentDefinitionData(
        id=1, name="researcher", instructions="Research.", max_execution_time=10
    )

    single_task_timeout = service._resolve_timeout_s(agent_definition, task_count=1)
    multi_task_timeout = service._resolve_timeout_s(agent_definition, task_count=3)

    assert single_task_timeout == 10 + 60.0
    assert multi_task_timeout == 10 * 3 + 60.0


def test_resolve_timeout_s_defaults_unchanged_for_single_task(redis_service_stub):
    service = AgentTaskService(
        redis_service=redis_service_stub, default_timeout=600.0
    )

    assert service._resolve_timeout_s(None) == 600.0
    assert service._resolve_timeout_s(None, task_count=1) == 600.0
    assert service._resolve_timeout_s(None, task_count=3) == 600.0 * 3


@pytest.mark.asyncio
async def test_run_task_resolves_timeout_for_single_task(
    redis_service_stub, task_node_data, monkeypatch
):
    service = AgentTaskService(
        redis_service=redis_service_stub, default_timeout=600.0, timeout_buffer_s=60.0
    )
    task_node_data.agent_definition.max_execution_time = 10
    captured_timeout = {}

    async def fake_dispatch(blob, timeout_s, stop_event, on_event=None):
        captured_timeout["value"] = timeout_s
        return {"final_text": "done"}

    monkeypatch.setattr(service, "_dispatch", fake_dispatch)

    await service.run_task(task_node_data, StopEvent())

    assert captured_timeout["value"] == 10 + 60.0


@pytest.mark.asyncio
async def test_run_agent_node_resolves_timeout_scaled_by_task_count(
    redis_service_stub, llm_data, monkeypatch
):
    service = AgentTaskService(
        redis_service=redis_service_stub, default_timeout=600.0, timeout_buffer_s=60.0
    )
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1,
            name="researcher",
            instructions="Research the topic.",
            llm=llm_data,
            max_execution_time=10,
        ),
        tasks=[
            AgentNodeTaskData(name="task_a", order=0, instructions="Write draft."),
            AgentNodeTaskData(name="task_b", order=1, instructions="Polish draft."),
            AgentNodeTaskData(name="task_c", order=2, instructions="Review draft."),
        ],
    )
    captured_timeout = {}

    async def fake_dispatch(blob, timeout_s, stop_event, on_event=None):
        captured_timeout["value"] = timeout_s
        return {"final_text": "done"}

    monkeypatch.setattr(service, "_dispatch", fake_dispatch)

    await service.run_agent_node(agent_node_data, StopEvent())

    assert captured_timeout["value"] == 10 * 3 + 60.0


def test_build_agent_node_request_blob(redis_service_stub, llm_data):
    service = AgentTaskService(redis_service=redis_service_stub)
    agent_node_data = AgentNodeData(
        node_name="agent_node_1",
        agent_definition=AgentDefinitionData(
            id=1, name="researcher", instructions="Research the topic.", llm=llm_data
        ),
        surface=CombinedSurfaceData(instructions="Never reveal secrets."),
        tasks=[
            AgentNodeTaskData(name="task_a", order=0, instructions="Write draft."),
            AgentNodeTaskData(
                name="task_b",
                order=1,
                instructions="Polish draft.",
                output_schema={"type": "object"},
                context_tasks=["task_a"],
            ),
        ],
    )

    blob = json.loads(service._build_agent_node_request_blob(agent_node_data))

    assert blob["run_type"] == "LIST_OF_TASKS"
    assert len(blob["agents"]) == 1
    instructions = blob["agents"][0]["instructions"]
    assert "Research the topic." in instructions
    assert "Never reveal secrets." in instructions

    tasks = blob["payload"]["tasks"]
    assert tasks[0] == {
        "name": "task_a",
        "instructions": "Write draft.",
        "output_schema": None,
        "context": [],
    }
    assert tasks[1] == {
        "name": "task_b",
        "instructions": "Polish draft.",
        "output_schema": {"type": "object"},
        "context": ["task_a"],
    }
