"""
Tests for ToolRegistryBuilder.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import AgentServiceError, DuplicateToolNameError
from app.tools.mcp.gateway import McpToolGateway
from app.tools.registry_builder import ToolRegistryBuilder
from app.tools.system_registry import (
    SystemToolRegistry,
    get_system_registry,
    system_tool,
)
from shared.models.agent_service import CollectionSpec, SearchConfigEntry, ToolResult
from shared.models.ai_providers import EmbedderConfigData, EmbedderData
from shared.models.knowledge import (
    GraphRagBasicSearchParams,
    GraphRagLocalSearchParams,
    GraphRagSearchConfig,
    NaiveRagSearchConfig,
)
from shared.models.tools import (
    ArgsSchema,
    CodeResultData,
    McpToolData,
    PythonCodeData,
    PythonCodeToolData,
)


@pytest.fixture(autouse=True)
def clear_global_registry():
    get_system_registry().clear()
    yield
    get_system_registry().clear()


def _fake_sandbox() -> MagicMock:
    return MagicMock()


def _fake_knowledge_client() -> MagicMock:
    return MagicMock()


def _embedder() -> EmbedderData:
    return EmbedderData(
        provider="openai",
        config=EmbedderConfigData(model="text-embedding-3-small"),
    )


def _naive_entry(rag_id: int = 1) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="naive",
        search_config=NaiveRagSearchConfig(),
        embedder=_embedder(),
    )


def _graph_basic_entry(rag_id: int = 2) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="graph",
        search_config=GraphRagSearchConfig(search_params=GraphRagBasicSearchParams()),
        embedder=_embedder(),
    )


def _graph_local_entry(rag_id: int = 3) -> SearchConfigEntry:
    return SearchConfigEntry(
        rag_id=rag_id,
        rag_type="graph",
        search_config=GraphRagSearchConfig(search_params=GraphRagLocalSearchParams()),
        embedder=_embedder(),
    )


def _collection_spec(
    name: str = "company_docs",
    entries: list[SearchConfigEntry] | None = None,
    description: str | None = None,
) -> CollectionSpec:
    return CollectionSpec(
        unique_name=f"collection:{name}",
        collection_id=10,
        name=name,
        description=description,
        search_configs=entries or [_naive_entry()],
    )


def _fake_gateway(return_value: str = "ok") -> McpToolGateway:
    gateway = MagicMock(spec=McpToolGateway)
    gateway.call = AsyncMock(return_value=return_value)
    return gateway


def _python_tool_data(
    name: str = "my_tool", python_code_overrides: dict | None = None
) -> PythonCodeToolData:
    return PythonCodeToolData(
        id=1,
        name=name,
        description="A tool.",
        args_schema=ArgsSchema(properties={}),
        python_code=PythonCodeData(
            venv_name=f"venv_pyt_{name}",
            code="def run(): return 'ok'",
            entrypoint="run",
            libraries=[],
            **(python_code_overrides or {}),
        ),
    )


def _mcp_tool_data(tool_name: str = "mcp_tool") -> McpToolData:
    return McpToolData(
        transport="http://localhost:8080/sse",
        tool_name=tool_name,
    )


def _register_system_tool(name: str) -> None:
    @system_tool(name=name, description=f"System tool {name}.", parameters_schema={})
    async def tool_func(args: dict) -> str:
        return name


async def test_system_tool_uses_clean_name():
    _register_system_tool("calculator")

    builder = ToolRegistryBuilder(_fake_sandbox())
    registry = builder.add_system_tools().build()

    names = [spec.name for spec in registry.tool_specs()]
    assert "calculator" in names


async def test_python_code_tool_uses_clean_name():
    builder = ToolRegistryBuilder(_fake_sandbox())
    registry = builder.add_python_code_tool(_python_tool_data("formatter")).build()

    names = [spec.name for spec in registry.tool_specs()]
    assert "formatter" in names


async def test_python_code_executor_forwards_storage_config_from_data():
    sandbox = _fake_sandbox()
    sandbox.submit = AsyncMock(
        return_value=CodeResultData(
            execution_id="exec-1",
            result_data="ok",
            stderr="",
            stdout="",
            returncode=0,
        )
    )

    data = _python_tool_data(
        "storage_tool",
        python_code_overrides={
            "use_storage": True,
            "storage_allowed_paths": ["reports/"],
            "storage_org_prefix": "org1",
            "session_id": 42,
        },
    )
    builder = ToolRegistryBuilder(sandbox)
    registry = builder.add_python_code_tool(data).build()

    await registry.execute("storage_tool", {})

    task = sandbox.submit.call_args[0][0]
    assert task.use_storage is True
    assert task.storage_allowed_paths == ["reports/"]
    assert task.storage_org_prefix == "org1"
    assert task.session_id == 42


async def test_mcp_tool_uses_clean_name():
    builder = ToolRegistryBuilder(_fake_sandbox(), _fake_gateway())
    registry = builder.add_mcp_tool(
        _mcp_tool_data("connector"),
        name="connector",
        description="An MCP tool.",
        args_schema={"type": "object", "properties": {}},
    ).build()

    names = [spec.name for spec in registry.tool_specs()]
    assert "connector" in names


async def test_sys_and_usr_same_name_now_collides():
    _register_system_tool("shared_name")

    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.add_system_tools()

    with pytest.raises(DuplicateToolNameError):
        builder.add_python_code_tool(_python_tool_data("shared_name"))


async def test_duplicate_usr_name_raises_duplicate_tool_name_error():
    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.add_python_code_tool(_python_tool_data("dup"))

    with pytest.raises(DuplicateToolNameError):
        builder.add_python_code_tool(_python_tool_data("dup"))


async def test_duplicate_sys_name_raises_duplicate_tool_name_error():
    from app.tools.system_registry import SystemToolEntry

    async def noop_executor(args: dict) -> ToolResult:
        return ToolResult(tool_call_id="", content="", is_error=False)

    registry_a = SystemToolRegistry()
    registry_a.register(
        SystemToolEntry(
            name="conflict",
            description="First.",
            parameters_schema={},
            executor=noop_executor,
        )
    )

    registry_b = SystemToolRegistry()
    registry_b.register(
        SystemToolEntry(
            name="conflict",
            description="Duplicate.",
            parameters_schema={},
            executor=noop_executor,
        )
    )

    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.add_system_tools(registry_a)

    with pytest.raises(DuplicateToolNameError):
        builder.add_system_tools(registry_b)


async def test_build_is_single_use():
    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.build()

    with pytest.raises(RuntimeError, match="single-use"):
        builder.build()


async def test_build_blocks_further_add_after_build():
    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.build()

    with pytest.raises(RuntimeError, match="single-use"):
        builder.add_python_code_tool(_python_tool_data("after_build"))


async def test_mcp_executor_calls_gateway_and_returns_result():
    gateway = _fake_gateway(return_value="tool output")
    builder = ToolRegistryBuilder(_fake_sandbox(), gateway)
    registry = builder.add_mcp_tool(
        _mcp_tool_data("my_mcp"),
        name="my_mcp",
        description="An MCP tool.",
        args_schema={},
    ).build()

    result = await registry.execute("my_mcp", {})

    assert result.is_error is False
    assert result.content == "tool output"


async def test_add_mcp_tool_without_gateway_raises_agent_service_error():
    builder = ToolRegistryBuilder(_fake_sandbox(), mcp_gateway=None)

    with pytest.raises(AgentServiceError, match="McpToolGateway"):
        builder.add_mcp_tool(
            _mcp_tool_data("my_mcp"),
            name="my_mcp",
            description="An MCP tool.",
            args_schema={},
        )


async def test_system_tool_executor_callable_via_registry():
    _register_system_tool("ping")

    builder = ToolRegistryBuilder(_fake_sandbox())
    registry = builder.add_system_tools().build()

    result = await registry.execute("ping", {})
    assert isinstance(result, ToolResult)
    assert result.is_error is False


async def test_tool_specs_returns_all_registered():
    _register_system_tool("spec_tool")

    builder = ToolRegistryBuilder(_fake_sandbox(), _fake_gateway())
    registry = (
        builder.add_system_tools()
        .add_python_code_tool(_python_tool_data("code_tool"))
        .add_mcp_tool(
            _mcp_tool_data("mcp_tool"),
            name="mcp_tool",
            description="MCP.",
            args_schema={},
        )
        .build()
    )

    specs = registry.tool_specs()
    names = {s.name for s in specs}
    assert names == {"spec_tool", "code_tool", "mcp_tool"}


async def test_tool_name_is_sanitized():
    builder = ToolRegistryBuilder(_fake_sandbox())
    registry = builder.add_python_code_tool(_python_tool_data("My Tool")).build()

    names = [spec.name for spec in registry.tool_specs()]
    assert "My_Tool" in names

    result = await registry.execute("My_Tool", {})
    assert isinstance(result, ToolResult)


async def test_sanitized_collision_raises():
    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.add_python_code_tool(_python_tool_data("My Tool"))

    with pytest.raises(DuplicateToolNameError):
        builder.add_python_code_tool(_python_tool_data("My_Tool"))


# ---------------------------------------------------------------------------
# add_knowledge_tools: fan-out
# ---------------------------------------------------------------------------


async def test_knowledge_tools_fan_out_naive_and_one_graph_tool():
    """Naive + graph-basic + graph-local (same rag_id) → 2 tools: _naive + _graph."""
    collection = _collection_spec(
        name="wiki",
        entries=[
            _naive_entry(rag_id=1),
            _graph_basic_entry(rag_id=2),
            _graph_local_entry(rag_id=2),
        ],
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    assert "search_wiki_naive" in names
    assert "search_wiki_graph" in names
    assert len(names) == 2


async def test_knowledge_tools_suffix_naive():
    collection = _collection_spec(name="docs", entries=[_naive_entry()])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    assert "search_docs_naive" in names


async def test_knowledge_tools_suffix_graph():
    collection = _collection_spec(name="docs", entries=[_graph_basic_entry(rag_id=2)])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    assert "search_docs_graph" in names


async def test_knowledge_tools_graph_schema_both_methods():
    """Graph tool with basic + local entries → enum contains both methods."""
    collection = _collection_spec(
        name="wiki",
        entries=[_graph_basic_entry(rag_id=2), _graph_local_entry(rag_id=2)],
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    schema = specs["search_wiki_graph"].parameters_schema
    methods = schema["properties"]["search_method"]["enum"]
    assert set(methods) == {"basic", "local"}
    assert schema["properties"]["search_method"]["default"] == "basic"


async def test_knowledge_tools_graph_schema_only_basic():
    """Graph tool with only basic entry → enum is ['basic'], default 'basic'."""
    collection = _collection_spec(name="docs", entries=[_graph_basic_entry(rag_id=2)])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    schema = specs["search_docs_graph"].parameters_schema
    methods = schema["properties"]["search_method"]["enum"]
    assert methods == ["basic"]
    assert schema["properties"]["search_method"]["default"] == "basic"


async def test_knowledge_tools_graph_schema_only_local():
    """Graph tool with only local entry → enum is ['local'], default 'local'."""
    collection = _collection_spec(name="docs", entries=[_graph_local_entry(rag_id=2)])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    schema = specs["search_docs_graph"].parameters_schema
    methods = schema["properties"]["search_method"]["enum"]
    assert methods == ["local"]
    assert schema["properties"]["search_method"]["default"] == "local"


async def test_knowledge_tools_graph_schema_search_method_not_required():
    """search_method must not be in 'required'."""
    collection = _collection_spec(
        name="wiki",
        entries=[_graph_basic_entry(rag_id=2), _graph_local_entry(rag_id=2)],
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    schema = specs["search_wiki_graph"].parameters_schema
    required = schema.get("required", [])
    assert "search_method" not in required
    assert "query" in required


async def test_knowledge_tools_two_graph_rags_separate_tools():
    """Two different rag_ids for graph → two separate _graph tools."""
    collection = _collection_spec(
        name="corp",
        entries=[_graph_basic_entry(rag_id=2), _graph_basic_entry(rag_id=3)],
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    assert "search_corp_graph" in names
    assert "search_corp_graph_3" in names


async def test_knowledge_tools_same_naive_type_dedup_appends_rag_id():
    """Two naive entries in one collection → second gets _{rag_id} suffix."""
    entries = [_naive_entry(rag_id=1), _naive_entry(rag_id=2)]
    collection = _collection_spec(name="corp", entries=entries)
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    assert "search_corp_naive" in names
    assert "search_corp_naive_2" in names


async def test_knowledge_tools_name_sanitization():
    collection = _collection_spec(name="My Docs!", entries=[_naive_entry()])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    # sanitized: "search_My_Docs__naive" or similar — suffix must be present
    assert any("_naive" in n for n in names)


async def test_knowledge_tools_suffix_survives_truncation():
    """Long collection name must not eat the suffix after truncation."""
    long_name = "a" * 60
    collection = _collection_spec(name=long_name, entries=[_naive_entry()])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    names = {spec.name for spec in registry.tool_specs()}
    name = next(iter(names))
    assert name.endswith("_naive")
    assert len(name) <= 64


async def test_knowledge_tools_description_naive():
    collection = _collection_spec(name="wiki", entries=[_naive_entry()])
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    desc = specs["search_wiki_naive"].description
    assert "Fast semantic chunk search" in desc
    assert "'wiki'" in desc
    assert "factual lookups" in desc


async def test_knowledge_tools_description_graph():
    collection = _collection_spec(
        name="wiki",
        entries=[_graph_basic_entry(rag_id=2), _graph_local_entry(rag_id=2)],
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    desc = specs["search_wiki_graph"].description
    assert "Knowledge-graph search" in desc
    assert "'wiki'" in desc
    assert "synthesis" in desc
    assert "entities" in desc


async def test_knowledge_tools_collection_description_appended():
    collection = _collection_spec(
        name="wiki",
        entries=[_naive_entry()],
        description="Internal company knowledge.",
    )
    builder = ToolRegistryBuilder(
        _fake_sandbox(), knowledge_client=_fake_knowledge_client()
    )
    registry = builder.add_knowledge_tools(collection).build()

    specs = {spec.name: spec for spec in registry.tool_specs()}
    desc = specs["search_wiki_naive"].description
    assert "Internal company knowledge." in desc


async def test_knowledge_tools_without_client_raises():
    collection = _collection_spec()
    builder = ToolRegistryBuilder(_fake_sandbox(), knowledge_client=None)

    with pytest.raises(AgentServiceError, match="KnowledgeClient"):
        builder.add_knowledge_tools(collection)
