"""
ToolRegistryBuilder: assembles the tools an agent run may call.

The sandbox, MCP gateway and knowledge service are external; they are replaced by
fakes that record what reaches them.
"""

from __future__ import annotations


import pytest
from app.exceptions import AgentServiceError, DuplicateToolNameError
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
from shared.models.storage_scope import StorageCredentials
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


class FakeSandbox:
    def __init__(self):
        self.tasks = []

    async def submit(self, task):
        self.tasks.append(task)
        return CodeResultData(execution_id=task.execution_id, result_data="code output", stderr="", stdout="", returncode=0)


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def call(self, data, args):
        self.calls.append((data, args))
        return "mcp output"


class FakeKnowledgeClient:
    async def search(self, target, query, timeout):
        return "answer"


class RecordingSink:
    def __init__(self):
        self.knowledge_tools: list[str] = []

    def register_knowledge_tool(self, name: str) -> None:
        self.knowledge_tools.append(name)


def _fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


def _fake_knowledge_client() -> FakeKnowledgeClient:
    return FakeKnowledgeClient()


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


def _fake_gateway() -> FakeGateway:
    return FakeGateway()


def _python_tool_data(
    name: str = "my_tool", python_code_overrides: dict | None = None
) -> PythonCodeToolData:
    return PythonCodeToolData(
        id=1,
        name=name,
        description="A tool.",
        args_schema=ArgsSchema(properties={}),
        python_code=PythonCodeData(
            code="def run(): return 'ok'",
            entrypoint="run",
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


async def test_every_tool_kind_is_exposed_under_its_name_and_runs():
    _register_system_tool("calculator")
    sandbox, gateway = _fake_sandbox(), _fake_gateway()

    registry = (
        ToolRegistryBuilder(sandbox, gateway)
        .add_system_tools()
        .add_python_code_tool(_python_tool_data("formatter"))
        .add_mcp_tool(_mcp_tool_data("connector"), name="connector", description="An MCP tool.", args_schema={})
        .build()
    )

    assert {spec.name for spec in registry.tool_specs()} == {"calculator", "formatter", "connector"}
    results = {name: await registry.execute(name, {}) for name in ("calculator", "formatter", "connector")}
    assert {name: (result.content, result.is_error) for name, result in results.items()} == {
        "calculator": ("calculator", False),
        "formatter": ("code output", False),
        "connector": ("mcp output", False),
    }
    assert len(sandbox.tasks) == len(gateway.calls) == 1


async def test_tool_name_is_sanitized_for_the_llm():
    registry = ToolRegistryBuilder(_fake_sandbox()).add_python_code_tool(_python_tool_data("My Tool")).build()

    assert [spec.name for spec in registry.tool_specs()] == ["My_Tool"]
    assert (await registry.execute("My_Tool", {})).content == "code output"


async def test_python_code_tool_runs_with_the_session_storage_scope():
    sandbox = _fake_sandbox()
    credentials = StorageCredentials(access_key="test-access", secret_key="test-secret")
    data = _python_tool_data(
        "storage_tool",
        python_code_overrides={
            "use_storage": True, "storage_allowed_paths": ["reports/"], "storage_org_prefix": "org1",
            "session_id": 42, "org_id": 77,
        },
    )
    registry = ToolRegistryBuilder(sandbox).add_python_code_tool(data, storage_credentials=credentials).build()

    await registry.execute("storage_tool", {})

    (task,) = sandbox.tasks
    assert (task.use_storage, task.storage_allowed_paths, task.storage_org_prefix, task.session_id, task.storage_credentials) == (
        True, ["reports/"], "org1", 42, credentials,
    )


def _system_registry_with(name: str) -> SystemToolRegistry:
    from app.tools.system_registry import SystemToolEntry

    async def noop_executor(args: dict) -> ToolResult:
        return ToolResult(tool_call_id="", content="", is_error=False)

    registry = SystemToolRegistry()
    registry.register(SystemToolEntry(name=name, description="d", parameters_schema={}, executor=noop_executor))
    return registry


@pytest.mark.parametrize(
    "add_twice",
    [
        lambda builder: builder.add_python_code_tool(_python_tool_data("dup")).add_python_code_tool(_python_tool_data("dup")),
        lambda builder: builder.add_system_tools(_system_registry_with("dup")).add_python_code_tool(_python_tool_data("dup")),
        lambda builder: builder.add_system_tools(_system_registry_with("dup")).add_system_tools(_system_registry_with("dup")),
        # Names collide after sanitizing, not only verbatim.
        lambda builder: builder.add_python_code_tool(_python_tool_data("My Tool")).add_python_code_tool(_python_tool_data("My_Tool")),
    ],
    ids=["user-user", "system-user", "system-system", "after-sanitizing"],
)
async def test_two_tools_with_one_name_are_refused(add_twice):
    with pytest.raises(DuplicateToolNameError):
        add_twice(ToolRegistryBuilder(_fake_sandbox()))


@pytest.mark.parametrize(
    "use_again",
    [lambda builder: builder.build(), lambda builder: builder.add_python_code_tool(_python_tool_data("after_build"))],
    ids=["build-again", "add-after-build"],
)
async def test_builder_is_single_use(use_again):
    builder = ToolRegistryBuilder(_fake_sandbox())
    builder.build()

    with pytest.raises(RuntimeError, match="single-use"):
        use_again(builder)


@pytest.mark.parametrize(
    ("builder", "add", "missing"),
    [
        (
            lambda: ToolRegistryBuilder(_fake_sandbox(), mcp_gateway=None),
            lambda builder: builder.add_mcp_tool(_mcp_tool_data("my_mcp"), name="my_mcp", description="d", args_schema={}),
            "McpToolGateway",
        ),
        (
            lambda: ToolRegistryBuilder(_fake_sandbox(), knowledge_client=None),
            lambda builder: builder.add_knowledge_tools(_collection_spec()),
            "KnowledgeClient",
        ),
    ],
    ids=["mcp", "knowledge"],
)
async def test_adding_a_tool_without_its_service_is_refused(builder, add, missing):
    with pytest.raises(AgentServiceError, match=missing):
        add(builder())


# ---------------------------------------------------------------------------
# Knowledge tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "entries", "expected_names"),
    [
        pytest.param(
            "wiki", [_naive_entry(rag_id=1), _graph_basic_entry(rag_id=2), _graph_local_entry(rag_id=2)],
            ["search_wiki_naive", "search_wiki_graph"], id="naive-and-one-graph-tool-per-rag",
        ),
        pytest.param("docs", [_naive_entry()], ["search_docs_naive"], id="naive"),
        pytest.param("docs", [_graph_basic_entry(rag_id=2)], ["search_docs_graph"], id="graph"),
        pytest.param(
            "corp", [_graph_basic_entry(rag_id=2), _graph_basic_entry(rag_id=3)],
            ["search_corp_graph", "search_corp_graph_3"], id="two-graph-rags",
        ),
        pytest.param(
            "corp", [_naive_entry(rag_id=1), _naive_entry(rag_id=2)],
            ["search_corp_naive", "search_corp_naive_2"], id="two-naive-rags",
        ),
        pytest.param("My Docs!", [_naive_entry()], ["search_My_Docs_naive"], id="sanitized"),
        # The suffix survives truncation to the 64-character limit.
        pytest.param("a" * 60, [_naive_entry()], ["search_" + "a" * 51 + "_naive"], id="long-name"),
    ],
)
async def test_knowledge_tool_names_and_the_sink_learns_each_of_them(name, entries, expected_names):
    sink = RecordingSink()
    registry = (
        ToolRegistryBuilder(_fake_sandbox(), knowledge_client=_fake_knowledge_client(), knowledge_sink=sink)
        .add_knowledge_tools(_collection_spec(name=name, entries=entries))
        .build()
    )

    assert [spec.name for spec in registry.tool_specs()] == expected_names
    # The emitter suppresses live tool events for exactly these names.
    assert sink.knowledge_tools == expected_names


@pytest.mark.parametrize(
    ("entries", "expected_methods", "expected_default"),
    [
        ([_graph_basic_entry(rag_id=2), _graph_local_entry(rag_id=2)], {"basic", "local"}, "basic"),
        ([_graph_basic_entry(rag_id=2)], {"basic"}, "basic"),
        ([_graph_local_entry(rag_id=2)], {"local"}, "local"),
    ],
    ids=["both", "only-basic", "only-local"],
)
async def test_graph_tool_offers_only_the_configured_search_methods(entries, expected_methods, expected_default):
    registry = (
        ToolRegistryBuilder(_fake_sandbox(), knowledge_client=_fake_knowledge_client())
        .add_knowledge_tools(_collection_spec(name="wiki", entries=entries))
        .build()
    )

    (spec,) = registry.tool_specs()
    search_method = spec.parameters_schema["properties"]["search_method"]
    assert (set(search_method["enum"]), search_method["default"]) == (expected_methods, expected_default)
    assert spec.parameters_schema["required"] == ["query"]


@pytest.mark.parametrize(
    ("entries", "description", "expected_fragments"),
    [
        ([_naive_entry()], None, ["Fast semantic chunk search", "'wiki'", "factual lookups"]),
        ([_graph_basic_entry(rag_id=2)], None, ["Knowledge-graph search", "'wiki'", "synthesis", "entities"]),
        ([_naive_entry()], "Internal company knowledge.", ["Internal company knowledge."]),
    ],
    ids=["naive", "graph", "collection-description-appended"],
)
async def test_knowledge_tool_description_tells_the_llm_when_to_use_it(entries, description, expected_fragments):
    registry = (
        ToolRegistryBuilder(_fake_sandbox(), knowledge_client=_fake_knowledge_client())
        .add_knowledge_tools(_collection_spec(name="wiki", entries=entries, description=description))
        .build()
    )

    (spec,) = registry.tool_specs()
    assert all(fragment in spec.description for fragment in expected_fragments)
