"""
Contract tests: AgentRequest validation and DataLoader correlation_id injection.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from app.data_loader import DataLoader
from app.exceptions import DataLoadError
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


# ---------------------------------------------------------------------------
# DataLoader injects correlation_id from envelope
# ---------------------------------------------------------------------------


class FakeKeyValueRedis:
    def __init__(self, values: dict[str, str]):
        self.values = values

    async def get(self, key):
        return self.values.get(key)

    async def aclose(self):
        pass


async def _load(monkeypatch, stored: dict[str, str]):
    from app import data_loader
    from shared.redis_streams import StreamEnvelope

    async def from_url(url, **kwargs):
        return FakeKeyValueRedis(stored)

    monkeypatch.setattr(data_loader.aioredis, "from_url", from_url)
    loader = DataLoader(host="localhost", port=6379)
    await loader.connect()
    envelope = StreamEnvelope(
        type="agent.run", correlation_id="injected-corr-id", payload={"request_key": "agent:request:42"}
    )
    return await loader.load(envelope)


async def test_data_loader_hydrates_the_request_with_the_envelopes_correlation_id(monkeypatch):
    """Crew stores the blob without correlation_id; it comes from the stream envelope."""
    blob = json.dumps(AgentRequest(correlation_id="ignored", **EXAMPLE_BLOB).model_dump(exclude={"correlation_id"}))

    request = await _load(monkeypatch, {"agent:request:42": blob})

    assert request.correlation_id == "injected-corr-id"
    assert request.run_type == RunType.SINGLE_TASK
    assert request.agents[0].id == 12


@pytest.mark.parametrize(
    ("stored", "message"),
    [({}, "No data found"), ({"agent:request:42": "{not json"}, "Invalid JSON")],
    ids=["missing-key", "malformed-json"],
)
async def test_data_loader_reports_an_unusable_blob(monkeypatch, stored, message):
    with pytest.raises(DataLoadError, match=message):
        await _load(monkeypatch, stored)


# ---------------------------------------------------------------------------
# agent.result payload key set is pinned (crew <-> agent wire contract)
# ---------------------------------------------------------------------------


async def test_agent_result_payload_key_set_includes_tasks():
    """Pin the exact key set published on 'agent.result' so crew's consumer
    can rely on it; 'tasks' must be present alongside the pre-existing keys."""
    published: list[dict] = []

    fake_client = MagicMock()

    async def capture_publish(
        stream: str,
        fields: dict,
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
        ttl_s: int | None = None,
    ) -> None:
        published.append(fields)

    fake_client.publish = capture_publish

    emitter = RedisStreamBatchEmitter(
        client=fake_client,
        result_stream_prefix="agent.results",
        correlation_id="corr-1",
        result_stream_ttl_s=3600,
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
        "warnings",
        "tasks",
    }
