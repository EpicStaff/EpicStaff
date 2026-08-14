"""
Integration tests for AgentResolver.

Verifies ref→pool resolution, error paths, unsupported tool types,
collection/s3 carried-not-resolved semantics, and multi-agent pool sharing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import (
    AgentServiceError,
    McpToolError,
    UnknownCollectionRefError,
    UnknownS3RefError,
    UnknownToolRefError,
)
from app.resources.resolver import AgentResolver
from app.tools.mcp.gateway import McpToolDescription, McpToolGateway
from shared.models.agent_service import (
    AgentRequest,
    AgentSpec,
    CollectionSpec,
    RunType,
    S3FileSpec,
    SearchConfigEntry,
)
from shared.models.ai_providers import (
    EmbedderConfigData,
    EmbedderData,
    LLMConfigData,
    LLMData,
)
from shared.models.knowledge import (
    GraphRagBasicSearchParams,
    GraphRagLocalSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
)
from shared.models.tools import (
    ArgsSchema,
    BaseToolData,
    McpToolData,
    PythonCodeData,
    PythonCodeToolData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm() -> LLMData:
    return LLMData(provider="openai", config=LLMConfigData(model="gpt-4o"))


def _embedder() -> EmbedderData:
    return EmbedderData(
        provider="openai",
        config=EmbedderConfigData(model="text-embedding-3-small"),
    )


def _agent_spec(
    tool_refs: list[str] | None = None,
    collection_refs: list[str] | None = None,
    s3_refs: list[int] | None = None,
    agent_id: int = 1,
) -> AgentSpec:
    return AgentSpec(
        id=agent_id,
        name="researcher",
        instructions="You research topics thoroughly.",
        llm=_llm(),
        tool_refs=tool_refs or [],
        collection_refs=collection_refs or [],
        s3_refs=s3_refs or [],
    )


def _python_tool_data(name: str = "my_tool") -> PythonCodeToolData:
    return PythonCodeToolData(
        id=1,
        name=name,
        description="A tool.",
        args_schema=ArgsSchema(properties={}),
        python_code=PythonCodeData(
            venv_name="venv_test",
            code="def run(): return 'ok'",
            entrypoint="run",
            libraries=[],
        ),
    )


def _base_tool(unique_name: str, data) -> BaseToolData:
    return BaseToolData(unique_name=unique_name, data=data)


def _mcp_tool_data(tool_name: str = "mcp_tool") -> McpToolData:
    return McpToolData(transport="http://localhost/sse", tool_name=tool_name)


def _naive_entry(rag_id: int = 3) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="naive",
        search_config=NaiveRagSearchConfig(),
        embedder=_embedder(),
    )


def _graph_basic_entry(rag_id: int = 4) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="graph",
        search_config=GraphRagSearchConfig(search_params=GraphRagBasicSearchParams()),
        embedder=_embedder(),
    )


def _graph_local_entry(rag_id: int = 5) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="graph",
        search_config=GraphRagSearchConfig(search_params=GraphRagLocalSearchParams()),
        embedder=_embedder(),
    )


def _collection_spec(
    unique_name: str = "collection:7",
    entries: list[SearchConfigEntry] | None = None,
) -> CollectionSpec:
    return CollectionSpec(
        unique_name=unique_name,
        collection_id=7,
        name="test_knowledge_base",
        search_configs=entries or [_naive_entry()],
    )


def _s3_spec(file_id: int = 88, path: str = "reports/q1.pdf") -> S3FileSpec:
    return S3FileSpec(id=file_id, path=path)


def _request(
    agents: list[AgentSpec],
    tools: list[BaseToolData] | None = None,
    collections: list[CollectionSpec] | None = None,
    s3_files: list[S3FileSpec] | None = None,
) -> AgentRequest:
    return AgentRequest(
        correlation_id="test-corr",
        run_type=RunType.SINGLE_TASK,
        agents=agents,
        tools=tools or [],
        collections=collections or [],
        s3_files=s3_files or [],
        payload={"prompt": "Go."},
    )


def _fake_gateway(
    description: str = "A tool.",
    input_schema: dict | None = None,
    raise_error: Exception | None = None,
) -> McpToolGateway:
    gateway = MagicMock(spec=McpToolGateway)

    if raise_error is not None:
        gateway.describe = AsyncMock(side_effect=raise_error)
    else:
        gateway.describe = AsyncMock(
            return_value=McpToolDescription(
                description=description,
                input_schema=input_schema or {},
            )
        )

    gateway.call = AsyncMock(return_value="ok")
    return gateway


def _fake_knowledge_client() -> MagicMock:
    return MagicMock()


def _resolver(
    gateway: McpToolGateway | None = None,
    knowledge_client=None,
) -> AgentResolver:
    return AgentResolver(
        sandbox=MagicMock(),
        mcp_gateway=gateway or _fake_gateway(),
        knowledge_client=knowledge_client or _fake_knowledge_client(),
    )


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


async def test_python_tool_ref_resolves_to_registry():
    agent = _agent_spec(tool_refs=["python-code-tool:1"])
    tool = _base_tool("python-code-tool:1", _python_tool_data())
    request = _request([agent], tools=[tool])

    resolved = await _resolver().resolve(agent, request)

    names = {spec.name for spec in resolved.tools.tool_specs()}
    assert "my_tool" in names


async def test_mcp_tool_ref_resolves_to_registry():
    agent = _agent_spec(tool_refs=["mcp-tool:4"])
    tool = _base_tool("mcp-tool:4", _mcp_tool_data("mcp_tool"))
    request = _request([agent], tools=[tool])

    resolved = await _resolver().resolve(agent, request)

    names = {spec.name for spec in resolved.tools.tool_specs()}
    assert "mcp_tool" in names


async def test_unknown_tool_ref_raises():
    agent = _agent_spec(tool_refs=["python-code-tool:99"])
    request = _request([agent], tools=[])

    with pytest.raises(UnknownToolRefError, match="python-code-tool:99"):
        await _resolver().resolve(agent, request)


async def test_unsupported_tool_prefix_raises_agent_service_error():
    from shared.models.tools import ConfiguredToolData, ToolConfigData

    agent = _agent_spec(tool_refs=["configured-tool:5"])
    tool = _base_tool(
        "configured-tool:5",
        ConfiguredToolData(
            name_alias="alias",
            tool_config=ToolConfigData(id=5),
        ),
    )
    request = _request([agent], tools=[tool])

    with pytest.raises(AgentServiceError, match="not supported"):
        await _resolver().resolve(agent, request)


async def test_mcp_gateway_failure_raises_mcp_tool_error():
    """Gateway describe() raises → resolver propagates McpToolError (fails the run)."""
    gateway = _fake_gateway(raise_error=McpToolError("server down"))
    agent = _agent_spec(tool_refs=["mcp-tool:7"])
    tool = _base_tool("mcp-tool:7", _mcp_tool_data("some_tool"))
    request = _request([agent], tools=[tool])

    with pytest.raises(McpToolError, match="server down"):
        await _resolver(gateway).resolve(agent, request)


# ---------------------------------------------------------------------------
# Collection resolution
# ---------------------------------------------------------------------------


async def test_collection_ref_registers_knowledge_tools():
    collection = _collection_spec("collection:7", entries=[_naive_entry()])
    agent = _agent_spec(collection_refs=["collection:7"])
    request = _request([agent], collections=[collection])

    resolved = await _resolver().resolve(agent, request)

    names = {spec.name for spec in resolved.tools.tool_specs()}
    assert any("_naive" in n for n in names)


async def test_collection_ref_multi_entry_fan_out():
    """Naive + graph-basic + graph-local (same rag_id) → 2 tools: _naive + _graph."""
    collection = _collection_spec(
        "collection:7",
        entries=[
            _naive_entry(rag_id=3),
            _graph_basic_entry(rag_id=4),
            _graph_local_entry(rag_id=4),
        ],
    )
    agent = _agent_spec(collection_refs=["collection:7"])
    request = _request([agent], collections=[collection])

    resolved = await _resolver().resolve(agent, request)

    names = {spec.name for spec in resolved.tools.tool_specs()}
    assert any("_naive" in n for n in names)
    assert any("_graph" in n and "_naive" not in n for n in names)
    assert len(names) == 2


async def test_unknown_collection_ref_raises():
    agent = _agent_spec(collection_refs=["collection:99"])
    request = _request([agent], collections=[])

    with pytest.raises(UnknownCollectionRefError, match="collection:99"):
        await _resolver().resolve(agent, request)


# ---------------------------------------------------------------------------
# S3 resolution
# ---------------------------------------------------------------------------


async def test_s3_ref_produces_single_system_attachment():
    s3 = _s3_spec(88, "reports/q1.pdf")
    agent = _agent_spec(s3_refs=[88])
    request = _request([agent], s3_files=[s3])

    resolved = await _resolver().resolve(agent, request)

    assert len(resolved.attachments) == 1
    attachment = resolved.attachments[0]
    assert attachment.source == "s3"
    assert attachment.role == "system"
    assert resolved.context.attachments == resolved.attachments


async def test_no_s3_refs_produces_no_attachments():
    agent = _agent_spec(s3_refs=[])
    request = _request([agent], s3_files=[])

    resolved = await _resolver().resolve(agent, request)

    assert resolved.attachments == []
    assert resolved.context.attachments == []


async def test_unknown_s3_ref_raises():
    agent = _agent_spec(s3_refs=[999])
    request = _request([agent], s3_files=[])

    with pytest.raises(UnknownS3RefError, match="999"):
        await _resolver().resolve(agent, request)


# ---------------------------------------------------------------------------
# Multi-agent pool sharing
# ---------------------------------------------------------------------------


async def test_two_agents_share_pool_each_gets_own_registry():
    """Two agents referencing the same python-code-tool:1 each get a registry
    with that tool registered; the pool entry is stored once."""
    tool = _base_tool("python-code-tool:1", _python_tool_data("shared_tool"))
    agent_a = _agent_spec(tool_refs=["python-code-tool:1"], agent_id=1)
    agent_b = _agent_spec(tool_refs=["python-code-tool:1"], agent_id=2)
    request = _request([agent_a, agent_b], tools=[tool])

    resolver = _resolver()
    resolved_a = await resolver.resolve(agent_a, request)
    resolved_b = await resolver.resolve(agent_b, request)

    names_a = {spec.name for spec in resolved_a.tools.tool_specs()}
    names_b = {spec.name for spec in resolved_b.tools.tool_specs()}
    assert "shared_tool" in names_a
    assert "shared_tool" in names_b
    assert resolved_a.tools is not resolved_b.tools


# ---------------------------------------------------------------------------
# ResolvedAgent structure
# ---------------------------------------------------------------------------


async def test_resolved_agent_carries_correct_agent_id():
    agent = _agent_spec(agent_id=42)
    request = _request([agent])

    resolved = await _resolver().resolve(agent, request)

    assert resolved.agent_id == 42


async def test_resolved_agent_context_has_empty_messages():
    """Resolver returns context with empty messages; prompt is built by the runner."""
    agent = _agent_spec()
    request = _request([agent])

    resolved = await _resolver().resolve(agent, request)

    assert resolved.context.messages == []


# ---------------------------------------------------------------------------
# knowledge_sink threading
# ---------------------------------------------------------------------------


async def test_knowledge_sink_threaded_to_registry_builder():
    """resolve(..., knowledge_sink=...) must reach ToolRegistryBuilder so
    knowledge tools registered during this resolve call notify the sink."""
    collection = _collection_spec("collection:7", entries=[_naive_entry()])
    agent = _agent_spec(collection_refs=["collection:7"])
    request = _request([agent], collections=[collection])
    sink = MagicMock()

    await _resolver().resolve(agent, request, knowledge_sink=sink)

    sink.register_knowledge_tool.assert_called_once_with(
        "search_test_knowledge_base_naive"
    )


async def test_resolve_without_knowledge_sink_still_works():
    agent = _agent_spec()
    request = _request([agent])

    resolved = await _resolver().resolve(agent, request)

    assert resolved.agent_id == agent.id
