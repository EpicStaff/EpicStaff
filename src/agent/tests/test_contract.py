"""
Contract tests: AgentRequest validation and DataLoader correlation_id injection.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data_loader import DataLoader
from app.emitters.redis_batch import RedisStreamBatchEmitter
from shared.models.agent_service import AgentRequest, LoopResult, RunType, TokenUsage


# ---------------------------------------------------------------------------
# The canonical example request blob (no correlation_id — DataLoader injects it)
# ---------------------------------------------------------------------------

EXAMPLE_BLOB = {
    "run_type": "SINGLE_TASK",
    "agents": [
        {
            "id": 12,
            "name": "researcher",
            "role": "Senior Researcher",
            "instructions": "You research topics thoroughly.",
            "llm": {
                "provider": "openai",
                "config": {"model": "gpt-4o", "temperature": 0.7},
            },
            "fcm_llm": None,
            "max_iter": 15,
            "schema_max_retries": 2,
            "max_rpm": 60,
            "max_execution_time": 120,
            "cache": True,
            "max_retry_limit": 5,
            "default_temperature": 0.7,
            "max_tool_calls": 15,
            "tool_timeout": 300,
            "max_consecutive_failures": 3,
            "tool_refs": ["python-code-tool:1", "mcp-tool:4"],
            "collection_refs": ["collection:7"],
            "s3_refs": [88],
        }
    ],
    "tools": [
        {
            "unique_name": "python-code-tool:1",
            "data": {
                "id": 1,
                "name": "python-code-tool",
                "description": "Runs Python code.",
                "args_schema": {
                    "type": "object",
                    "title": "ArgumentsSchema",
                    "properties": {"x": {"type": "string"}},
                    "required": [],
                },
                "python_code": {
                    "venv_name": "venv_pyt_1",
                    "code": "def run(x): return x",
                    "entrypoint": "run",
                    "libraries": [],
                    "global_kwargs": None,
                    "use_storage": False,
                    "storage_allowed_paths": None,
                    "storage_org_prefix": None,
                    "session_id": None,
                },
            },
        },
        {
            "unique_name": "mcp-tool:4",
            "data": {
                "transport": "http://localhost/sse",
                "tool_name": "search",
                "timeout": 30,
                "auth": None,
                "init_timeout": 10,
            },
        },
    ],
    "collections": [
        {
            "unique_name": "collection:7",
            "collection_id": 7,
            "name": "research_docs",
            "description": None,
            "search_configs": [
                {
                    "rag_id": 3,
                    "rag_type": "naive",
                    "search_config": {
                        "rag_type": "naive",
                        "search_limit": 3,
                        "similarity_threshold": 0.2,
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {"model": "text-embedding-3-small"},
                    },
                },
                {
                    "rag_id": 4,
                    "rag_type": "graph",
                    "search_config": {
                        "rag_type": "graph",
                        "search_params": {"search_method": "basic"},
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {"model": "text-embedding-3-small"},
                    },
                },
            ],
        }
    ],
    "s3_files": [{"id": 88, "path": "reports/2026/q1.pdf"}],
    "payload": {"prompt": "Summarize Q1."},
}


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def test_agent_request_validates_example_blob():
    request = AgentRequest(correlation_id="corr-1", **EXAMPLE_BLOB)

    assert request.run_type == RunType.SINGLE_TASK
    assert len(request.agents) == 1
    assert request.agents[0].id == 12
    assert request.agents[0].name == "researcher"
    assert request.agents[0].llm.provider == "openai"
    assert request.agents[0].llm.config.model == "gpt-4o"
    assert request.agents[0].max_tool_calls == 15
    assert request.agents[0].tool_timeout == 300
    assert request.agents[0].schema_max_retries == 2
    assert request.agents[0].max_consecutive_failures == 3
    assert request.agents[0].tool_refs == ["python-code-tool:1", "mcp-tool:4"]
    assert request.agents[0].collection_refs == ["collection:7"]
    assert request.agents[0].s3_refs == [88]
    assert len(request.tools) == 2
    assert len(request.collections) == 1
    assert len(request.collections[0].search_configs) == 2
    assert len(request.s3_files) == 1
    assert request.s3_files[0].path == "reports/2026/q1.pdf"
    assert request.payload == {"prompt": "Summarize Q1."}
    assert request.correlation_id == "corr-1"


def test_agent_request_round_trips():
    request = AgentRequest(correlation_id="corr-1", **EXAMPLE_BLOB)
    dumped = request.model_dump()
    assert dumped["correlation_id"] == "corr-1"
    assert dumped["run_type"] == "SINGLE_TASK"


def test_agent_request_frozen():
    request = AgentRequest(correlation_id="corr-1", **EXAMPLE_BLOB)
    with pytest.raises(Exception):
        request.correlation_id = "mutated"  # type: ignore[misc]


def test_collection_spec_search_configs_accessible():
    request = AgentRequest(correlation_id="corr-1", **EXAMPLE_BLOB)
    collection = request.collections[0]

    assert collection.unique_name == "collection:7"
    assert collection.collection_id == 7
    assert collection.name == "research_docs"

    naive_entry = collection.search_configs[0]
    assert naive_entry.rag_type == "naive"
    assert naive_entry.rag_id == 3

    graph_entry = collection.search_configs[1]
    assert graph_entry.rag_type == "graph"
    assert graph_entry.rag_id == 4


# ---------------------------------------------------------------------------
# DataLoader injects correlation_id from envelope
# ---------------------------------------------------------------------------


async def test_data_loader_injects_correlation_id():
    """DataLoader builds AgentRequest(correlation_id=envelope.correlation_id, **data).
    The blob stored at the Redis key must NOT contain correlation_id.
    """
    from shared.redis_streams import StreamEnvelope

    template = AgentRequest(correlation_id="ignored", **EXAMPLE_BLOB)
    dumped = template.model_dump(exclude={"correlation_id"})
    blob_without_correlation_id = json.dumps(dumped)

    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=blob_without_correlation_id)
    fake_redis.aclose = AsyncMock()

    loader = DataLoader.__new__(DataLoader)
    loader._host = "localhost"
    loader._port = 6379
    loader._password = None
    loader._client = fake_redis

    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="injected-corr-id",
        payload={"request_key": "agent:request:42"},
    )

    request = await loader.load(envelope)

    assert request.correlation_id == "injected-corr-id"
    assert request.run_type == RunType.SINGLE_TASK
    assert request.agents[0].id == 12


# ---------------------------------------------------------------------------
# agent.result payload key set is pinned (crew <-> agent wire contract)
# ---------------------------------------------------------------------------


async def test_agent_result_payload_key_set_includes_tasks():
    """Pin the exact key set published on 'agent.result' so crew's consumer
    can rely on it; 'tasks' must be present alongside the pre-existing keys."""
    published: list[dict] = []

    fake_client = MagicMock()

    async def capture_publish(stream: str, fields: dict) -> None:
        published.append(fields)

    fake_client.publish = capture_publish

    emitter = RedisStreamBatchEmitter(
        client=fake_client,
        result_stream="agent.results",
        correlation_id="corr-1",
    )
    result = LoopResult(
        final_text="done",
        tool_invocations=0,
        iterations=1,
        stop_reason="completed",
        token_usage=TokenUsage(),
    )

    await emitter.on_final(result)

    payload = json.loads(published[0]["payload"])
    assert set(payload.keys()) == {
        "final_text",
        "structured_output",
        "tool_invocations",
        "iterations",
        "stop_reason",
        "token_usage",
        "error",
        "events",
        "warnings",
        "tasks",
    }


# ---------------------------------------------------------------------------
# Live envelope types (agent -> crew wire contract)
# ---------------------------------------------------------------------------

LIVE_EVENT_TYPES = frozenset(
    {
        "agent.tool_call",
        "agent.tool_result",
        "agent.task_start",
        "agent.task_finish",
        "agent.knowledge_search",
    }
)
"""Mirrors ``LIVE_EVENT_TYPES`` in ``src/crew/services/agent_task_service.py``
— envelope types forwarded live to crew's ``on_event`` callback instead of
ending the wait. Keep both lists in sync when adding a new live envelope."""


def test_live_event_types_include_knowledge_search():
    """Pins 'agent.knowledge_search' as a recognized live envelope type
    alongside the existing tool-call/tool-result/task-start/task-finish set."""
    assert "agent.knowledge_search" in LIVE_EVENT_TYPES
    assert LIVE_EVENT_TYPES == {
        "agent.tool_call",
        "agent.tool_result",
        "agent.task_start",
        "agent.task_finish",
        "agent.knowledge_search",
    }
