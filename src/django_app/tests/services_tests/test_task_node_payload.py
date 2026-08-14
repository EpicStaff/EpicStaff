"""
Tests for passing TaskNode into the crew session payload with combined surfaces.

Covers:
- NodeSurfaceService.build_combined_surface (catalog + inline surface combination)
- SessionManagerService._build_graph_data TaskNode conversion end-to-end
- Cross-service round-trip parseability (SessionData -> JSON -> SessionData)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agents.exceptions import SurfaceValidationError
from tables.models import EmbeddingConfig, EmbeddingModel
from agents.models import (
    AgentDefinition,
    Surface,
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphLocalSearchConfig,
    SurfaceMcpTool,
)
from agents.models.agent_models import DefaultAgentDefinitionConfig
from agents.models.surface_models import (
    InlineSurface,
    InlineSurfaceStorageItem,
    SurfaceNaiveSearchConfig,
    SurfaceKnowledge,
    SurfacePythonTool,
    SurfaceStorageItem,
    ToolMode,
)
from tables.models.graph_models import (
    AgentNode,
    Edge,
    Graph,
    GraphStorageFile,
    StartNode,
    StorageFile,
    TaskNode,
)
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization
from agents.services.node_surface_service import NodeSurfaceService
from tables.services.agent_node_payload_service import AgentNodePayloadService
from tables.services.converter_service import ConverterService
from tables.services.session_manager_service import SessionManagerService
from src.shared.models import (
    AgentRequest,
    AgentSpec,
    CombinedSurfaceData,
    GraphData,
    RunType,
    SessionData,
)


@pytest.fixture
def org(db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="task-node-payload-graph", org=org)


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="task-node-payload-agent",
        instructions="do things",
    )


@pytest.fixture
def surface_a(db, org):
    return Surface.objects.create(
        organization=org,
        name="task-node-payload-surface-a",
        instructions="be concise",
    )


@pytest.fixture
def surface_b(db, org):
    return Surface.objects.create(
        organization=org,
        name="task-node-payload-surface-b",
        instructions="use bullet points",
    )


@pytest.fixture
def py_tool(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="task-node-payload-py-tool", description="test", python_code=code
    )


@pytest.fixture
def storage_file(db, org):
    return StorageFile.objects.create(
        org=org, name="task-node-payload-file", path="task-node-payload/a.txt"
    )


@pytest.fixture
def storage_py_tool(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="task-node-payload-storage-py-tool",
        description="test",
        python_code=code,
        use_storage=True,
    )


@pytest.fixture
def mcp_tool(db, org):
    return McpTool.objects.create(
        org=org,
        name="task-node-payload-mcp-tool",
        transport="https://example.com/mcp",
        tool_name="search",
    )


@pytest.fixture
def task_node(graph):
    return TaskNode.objects.create(graph=graph, node_name="task-node-payload")


def wire_entrypoint(graph, task_node):
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(
        graph=graph, start_node_id=start_node.id, end_node_id=task_node.id
    )


class TestNodeSurfaceService:
    @pytest.mark.django_db
    def test_two_catalog_surfaces_combined_with_deny_precedence(
        self, task_node, surface_a, surface_b, py_tool
    ):
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        SurfacePythonTool.objects.create(
            surface=surface_b, python_tool=py_tool, mode=ToolMode.DENY
        )
        task_node.surface_list.set([surface_a, surface_b])

        combined = NodeSurfaceService.build_combined_surface(task_node)

        assert combined["instructions"] == "be concise\n\nuse bullet points"
        tools_by_id = {t["python_tool"]: t["mode"] for t in combined["python_tools"]}
        assert tools_by_id[py_tool.pk] == "deny"

    @pytest.mark.django_db
    def test_inline_surface_only_matches_inline_content_exactly(self, task_node):
        InlineSurface.objects.create(
            task_node=task_node, instructions="inline instructions"
        )

        combined = NodeSurfaceService.build_combined_surface(task_node)

        assert combined["instructions"] == "inline instructions"
        assert combined["python_tools"] == []
        assert combined["storage_items"] == []

    @pytest.mark.django_db
    def test_catalog_and_inline_conflicting_storage_deny_wins_instructions_ordered(
        self, task_node, surface_a, storage_file
    ):
        SurfaceStorageItem.objects.create(
            surface=surface_a, storage_file=storage_file, can_view="allow"
        )
        task_node.surface_list.set([surface_a])
        inline_surface = InlineSurface.objects.create(
            task_node=task_node, instructions="inline instructions"
        )
        InlineSurfaceStorageItem.objects.create(
            inline_surface=inline_surface, storage_file=storage_file, can_view="deny"
        )

        combined = NodeSurfaceService.build_combined_surface(task_node)

        assert combined["instructions"] == "be concise\n\ninline instructions"
        items_by_id = {i["storage_file"]: i for i in combined["storage_items"]}
        assert items_by_id[storage_file.pk]["can_view"] == "deny"

    @pytest.mark.django_db
    def test_no_surfaces_produces_empty_combined_surface_data(self, task_node):
        combined = NodeSurfaceService.build_combined_surface(task_node)

        assert CombinedSurfaceData(**combined) == CombinedSurfaceData()


class TestBuildGraphDataTaskNode:
    @pytest.mark.django_db
    def test_task_node_converted_with_agent_defaults_and_surfaces(
        self, graph, task_node, agent, surface_a, surface_b, py_tool
    ):
        DefaultAgentDefinitionConfig.objects.update_or_create(
            pk=1,
            defaults={
                "max_iter": 15,
                "max_rpm": 20,
                "max_execution_time": 300,
                "cache": True,
                "max_retry_limit": 3,
                "default_temperature": 0.7,
                "max_tool_calls": 10,
                "tool_timeout": 120,
                "max_consecutive_failures": 4,
                "schema_max_retries": 2,
            },
        )
        agent.max_iter = None
        agent.default_temperature = None
        agent.max_rpm = 5
        agent.max_tool_calls = None
        agent.tool_timeout = None
        agent.max_consecutive_failures = None
        agent.schema_max_retries = None
        agent.save()

        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        SurfacePythonTool.objects.create(
            surface=surface_b, python_tool=py_tool, mode=ToolMode.DENY
        )
        task_node.agent_definition = agent
        task_node.instructions = "do the task"
        task_node.save()
        task_node.surface_list.set([surface_a, surface_b])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        assert len(graph_data.task_node_list) == 1
        task_data = graph_data.task_node_list[0]
        assert task_data.instructions == "do the task"
        assert task_data.agent_definition.id == agent.pk
        assert task_data.agent_definition.max_iter == 15
        assert task_data.agent_definition.max_rpm == 5
        assert task_data.agent_definition.default_temperature == 0.7
        assert task_data.agent_definition.max_tool_calls == 10
        assert task_data.agent_definition.tool_timeout == 120
        assert task_data.agent_definition.max_consecutive_failures == 4
        assert task_data.agent_definition.schema_max_retries == 2
        tools_by_id = {t.python_tool: t.mode for t in task_data.surface.python_tools}
        assert tools_by_id[py_tool.pk] == "deny"

    @pytest.mark.django_db
    def test_agent_explicit_tool_limits_override_defaults(
        self, graph, task_node, agent
    ):
        DefaultAgentDefinitionConfig.objects.update_or_create(
            pk=1,
            defaults={
                "max_tool_calls": 10,
                "tool_timeout": 120,
                "max_consecutive_failures": 4,
                "schema_max_retries": 5,
            },
        )
        agent.max_tool_calls = 7
        agent.tool_timeout = 45
        agent.max_consecutive_failures = 2
        agent.schema_max_retries = 0
        agent.save()
        task_node.agent_definition = agent
        task_node.save()
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.agent_definition.max_tool_calls == 7
        assert task_data.agent_definition.tool_timeout == 45
        assert task_data.agent_definition.max_consecutive_failures == 2
        assert task_data.agent_definition.schema_max_retries == 0

    def test_graph_data_without_task_node_list_defaults_to_empty(self):
        graph_data = GraphData(name="g", entrypoint="test", end_node=None)
        assert graph_data.task_node_list == []

    @pytest.mark.django_db
    def test_task_node_input_map_passed_through(self, graph, task_node):
        task_node.instructions = "Write about {topic}"
        task_node.input_map = {"topic": "variables.topic"}
        task_node.save()
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.input_map == {"topic": "variables.topic"}

    @pytest.mark.django_db
    def test_task_node_default_input_map_is_empty(self, graph, task_node):
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.input_map == {}


class TestDefaultAgentDefinitionConfigSeededDefaults:
    @pytest.mark.django_db
    def test_null_exec_fields_fall_back_to_seeded_defaults(
        self, graph, task_node, agent
    ):
        agent.max_iter = None
        agent.max_rpm = None
        agent.max_execution_time = None
        agent.cache = None
        agent.max_retry_limit = None
        agent.default_temperature = None
        agent.schema_max_retries = None
        agent.save()
        task_node.agent_definition = agent
        task_node.save()
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        agent_data = graph_data.task_node_list[0].agent_definition
        assert agent_data.max_iter == 25
        assert agent_data.max_rpm == 10
        assert agent_data.max_execution_time == 60
        assert agent_data.cache is False
        assert agent_data.max_retry_limit == 3
        assert agent_data.default_temperature == 0.7
        assert agent_data.schema_max_retries == 2

    @pytest.mark.django_db
    def test_explicit_exec_fields_are_not_overridden_by_seeded_defaults(
        self, graph, task_node, agent
    ):
        agent.max_iter = 99
        agent.max_rpm = 42
        agent.max_execution_time = 120
        agent.cache = True
        agent.max_retry_limit = 7
        agent.default_temperature = 0.2
        agent.schema_max_retries = 9
        agent.save()
        task_node.agent_definition = agent
        task_node.save()
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        agent_data = graph_data.task_node_list[0].agent_definition
        assert agent_data.max_iter == 99
        assert agent_data.max_rpm == 42
        assert agent_data.max_execution_time == 120
        assert agent_data.cache is True
        assert agent_data.max_retry_limit == 7
        assert agent_data.default_temperature == 0.2
        assert agent_data.schema_max_retries == 9


class TestSessionDataRoundTrip:
    @pytest.mark.django_db
    def test_task_node_list_survives_json_round_trip(
        self, graph, task_node, agent, surface_a
    ):
        task_node.agent_definition = agent
        task_node.instructions = "round trip"
        task_node.input_map = {"topic": "variables.topic"}
        task_node.save()
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)
        session_data = SessionData(id=1, graph=graph_data)

        parsed = SessionData.model_validate_json(session_data.model_dump_json())

        assert len(parsed.graph.task_node_list) == 1
        assert parsed.graph.task_node_list[0].instructions == "round trip"
        assert parsed.graph.task_node_list[0].agent_definition.id == agent.pk
        assert parsed.graph.task_node_list[0].input_map == {"topic": "variables.topic"}


class TestSurfaceValidationErrorPropagation:
    @pytest.mark.django_db
    def test_conflicting_rag_configs_across_surfaces_raise(
        self, graph, task_node, surface_a, surface_b, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-conflict-collection"
        )
        BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )

        knowledge_a = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge_a, search_limit=5, similarity_threshold="0.30"
        )
        knowledge_b = SurfaceKnowledge.objects.create(
            surface=surface_b, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge_b, search_limit=10, similarity_threshold="0.50"
        )
        task_node.surface_list.set([surface_a, surface_b])
        wire_entrypoint(graph, task_node)

        with pytest.raises(SurfaceValidationError):
            SessionManagerService()._build_graph_data(graph)


class TestDecimalCoercion:
    @pytest.mark.django_db
    def test_similarity_threshold_decimal_coerces_to_float(
        self, graph, task_node, surface_a, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-decimal-collection"
        )
        BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge,
            search_limit=3,
            similarity_threshold=Decimal("0.20"),
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        naive_config = task_data.surface.knowledge[0].naive_search_config
        assert naive_config.similarity_threshold == pytest.approx(0.20)
        assert isinstance(naive_config.similarity_threshold, float)


class TestAgentDefinitionLLMHydration:
    @pytest.mark.django_db
    def test_agent_llm_hydrated_fcm_llm_absent(
        self, graph, task_node, agent, llm_config
    ):
        agent.llm_config = llm_config
        agent.save()
        task_node.agent_definition = agent
        task_node.save()
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.agent_definition.llm is not None
        assert task_data.agent_definition.llm.provider == "openai"
        assert task_data.agent_definition.llm.config.model == llm_config.model.name
        assert task_data.agent_definition.llm.config.api_key == llm_config.api_key
        assert task_data.agent_definition.fcm_llm is None
        assert task_data.agent_definition.llm_config_id == llm_config.pk


class TestToolPool:
    @pytest.mark.django_db
    def test_allow_python_tool_included_with_args_schema(
        self, graph, task_node, surface_a, py_tool
    ):
        py_tool.variables = [
            {
                "name": "query",
                "type": "string",
                "description": "search text",
                "default_value": None,
                "input_type": "agent_input",
                "required": True,
            },
            {
                "name": "api_key",
                "type": "string",
                "description": "",
                "default_value": None,
                "input_type": "user_input",
                "required": True,
            },
        ]
        py_tool.save()
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert len(task_data.tools) == 1
        tool = task_data.tools[0]
        assert tool.unique_name == f"python-code-tool:{py_tool.pk}"
        assert "query" in tool.data.args_schema.properties
        assert "api_key" not in tool.data.args_schema.properties
        assert tool.data.args_schema.required == ["query"]

    @pytest.mark.django_db
    def test_deny_wins_over_allow_excludes_tool(
        self, graph, task_node, surface_a, surface_b, py_tool
    ):
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        SurfacePythonTool.objects.create(
            surface=surface_b, python_tool=py_tool, mode=ToolMode.DENY
        )
        task_node.surface_list.set([surface_a, surface_b])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.tools == []

    @pytest.mark.django_db
    def test_allow_mcp_tool_included(self, graph, task_node, surface_a, mcp_tool):
        SurfaceMcpTool.objects.create(
            surface=surface_a, mcp_tool=mcp_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert len(task_data.tools) == 1
        assert task_data.tools[0].unique_name == f"mcp-tool:{mcp_tool.pk}"


class TestS3Pool:
    @pytest.mark.django_db
    def test_allow_view_flag_included_with_flags_metadata(
        self, graph, task_node, surface_a, storage_file
    ):
        SurfaceStorageItem.objects.create(
            surface=surface_a, storage_file=storage_file, can_view="allow"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert len(task_data.s3_files) == 1
        s3_file = task_data.s3_files[0]
        assert s3_file.id == storage_file.pk
        assert s3_file.path == storage_file.path
        assert s3_file.metadata["flags"]["can_view"] == "allow"
        assert s3_file.metadata["flags"]["can_list"] == "unset"

    @pytest.mark.django_db
    def test_all_unset_or_deny_only_excluded(
        self, graph, task_node, surface_a, storage_file
    ):
        SurfaceStorageItem.objects.create(
            surface=surface_a, storage_file=storage_file, can_edit="deny"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.s3_files == []


class TestCollectionPool:
    @pytest.mark.django_db
    def test_naive_collection_hydrated_with_rag_id_and_embedder(
        self, graph, task_node, surface_a, embedding_config, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-naive-collection"
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        naive_rag = NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.35"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert len(task_data.collections) == 1
        collection_spec = task_data.collections[0]
        assert collection_spec.unique_name == f"collection:{collection.pk}"
        assert len(collection_spec.search_configs) == 1
        entry = collection_spec.search_configs[0]
        assert entry.rag_id == naive_rag.naive_rag_id
        assert entry.rag_type == "naive"
        assert entry.search_config.search_limit == 5
        assert entry.search_config.similarity_threshold == pytest.approx(0.35)
        assert entry.embedder is not None

    @pytest.mark.django_db
    def test_graph_basic_and_local_share_rag_id_with_search_method(
        self, graph, task_node, surface_a, embedding_config, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-graph-collection"
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.GRAPH, source_collection=collection
        )
        graph_rag = GraphRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=GraphRag.GraphRagStatus.COMPLETED,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceGraphBasicSearchConfig.objects.create(
            surface_knowledge=knowledge, prompt="basic prompt", k=7
        )
        SurfaceGraphLocalSearchConfig.objects.create(
            surface_knowledge=knowledge, prompt="local prompt", top_k_entities=4
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert len(task_data.collections) == 1
        entries = task_data.collections[0].search_configs
        assert len(entries) == 2
        assert {e.rag_id for e in entries} == {graph_rag.graph_rag_id}
        assert {e.rag_type for e in entries} == {"graph"}
        search_methods = {e.search_config.search_params.search_method for e in entries}
        assert search_methods == {"basic", "local"}

    @pytest.mark.django_db
    def test_naive_rag_without_embedder_skipped_no_crash(
        self, graph, task_node, surface_a, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-no-embedder-collection"
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        NaiveRag.objects.create(base_rag_type=base_rag_type, embedder=None)
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=3, similarity_threshold="0.20"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.collections == []

    @pytest.mark.django_db
    def test_collection_description_populated_on_spec(
        self, graph, task_node, surface_a, embedding_config, org
    ):
        collection = SourceCollection.objects.create(
            org=org,
            collection_name="task-node-payload-described-collection",
            description="Product FAQ knowledge base.",
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.35"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.collections[0].description == "Product FAQ knowledge base."

    @pytest.mark.django_db
    def test_blank_collection_description_yields_none_on_spec(
        self, graph, task_node, surface_a, embedding_config, org
    ):
        collection = SourceCollection.objects.create(
            org=org, collection_name="task-node-payload-blank-description-collection"
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.35"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        assert task_data.collections[0].description is None

    @pytest.mark.django_db
    def test_completed_rag_preferred_over_newer_non_completed(
        self, graph, task_node, surface_a, embedding_config, org
    ):
        collection = SourceCollection.objects.create(
            org=org,
            collection_name="task-node-payload-completed-preference-collection",
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        completed_rag = NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.PROCESSING,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=3, similarity_threshold="0.20"
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        entry = task_data.collections[0].search_configs[0]
        assert entry.rag_id == completed_rag.naive_rag_id


class TestAgentNodeCollectionDescription:
    """CollectionSpec.description flows through the agent-node payload path too,
    since AgentNodePayloadService shares _build_collection_pool with TaskNode."""

    @pytest.mark.django_db
    def test_collection_description_populated_for_agent_node(
        self, graph, surface_a, embedding_config, org
    ):
        agent_node = AgentNode.objects.create(
            graph=graph, node_name="agent-node-payload-described"
        )
        collection = SourceCollection.objects.create(
            org=org,
            collection_name="agent-node-payload-described-collection",
            description="Support runbooks.",
        )
        base_rag_type = BaseRagType.objects.create(
            rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
        )
        NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
        )
        knowledge = SurfaceKnowledge.objects.create(
            surface=surface_a, collection=collection
        )
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.35"
        )
        agent_node.surface_list.set([surface_a])

        agent_node_data = AgentNodePayloadService(
            ConverterService()
        ).build_agent_node_data(
            agent_node=agent_node,
            node_name=agent_node.node_name,
            graph_id=graph.pk,
            session_id=None,
        )

        assert agent_node_data.collections[0].description == "Support runbooks."


class TestPoolsContractCrossCheck:
    @pytest.mark.django_db
    def test_pools_and_agent_spec_validate_as_agent_request(
        self, graph, task_node, agent, surface_a, py_tool, llm_config
    ):
        agent.llm_config = llm_config
        agent.save()
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        task_node.agent_definition = agent
        task_node.instructions = "cross-check task"
        task_node.save()
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)
        task_data = graph_data.task_node_list[0]

        agent_spec = AgentSpec(
            id=task_data.agent_definition.id,
            name=task_data.agent_definition.name,
            instructions=task_data.agent_definition.instructions,
            llm=task_data.agent_definition.llm,
            fcm_llm=task_data.agent_definition.fcm_llm,
            tool_refs=[t.unique_name for t in task_data.tools],
            collection_refs=[c.unique_name for c in task_data.collections],
            s3_refs=[f.id for f in task_data.s3_files],
        )
        request = AgentRequest(
            correlation_id="cross-check",
            run_type=RunType.SINGLE_TASK,
            agents=[agent_spec],
            tools=task_data.tools,
            collections=task_data.collections,
            s3_files=task_data.s3_files,
        )

        assert request.agents[0].tool_refs == [f"python-code-tool:{py_tool.pk}"]

    @pytest.mark.django_db
    def test_task_node_pools_survive_json_round_trip(
        self, graph, task_node, surface_a, py_tool
    ):
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)
        session_data = SessionData(id=1, graph=graph_data)

        parsed = SessionData.model_validate_json(session_data.model_dump_json())

        parsed_task_data = parsed.graph.task_node_list[0]
        assert len(parsed_task_data.tools) == 1
        assert parsed_task_data.tools[0].unique_name == f"python-code-tool:{py_tool.pk}"


class TestStorageToolAllowedPathsScopedToSurface:
    """storage_allowed_paths baked into a use_storage python tool must come from
    the node's SURFACE storage items, not from every GraphStorageFile attached
    to the graph."""

    @pytest.mark.django_db
    def test_graph_file_not_granted_by_surface_is_excluded(
        self, graph, task_node, surface_a, storage_file, storage_py_tool
    ):
        GraphStorageFile.objects.create(graph=graph, storage_file=storage_file)
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=storage_py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        tool = task_data.tools[0]
        assert storage_file.path not in tool.data.python_code.storage_allowed_paths

    @pytest.mark.django_db
    def test_surface_granted_file_is_included(
        self, graph, task_node, surface_a, storage_file, storage_py_tool
    ):
        SurfaceStorageItem.objects.create(
            surface=surface_a, storage_file=storage_file, can_view="allow"
        )
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=storage_py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        tool = task_data.tools[0]
        assert tool.data.python_code.storage_allowed_paths == [storage_file.path]

    @pytest.mark.django_db
    def test_no_surface_storage_items_yields_empty_list_not_none(
        self, graph, task_node, surface_a, storage_py_tool
    ):
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=storage_py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        tool = task_data.tools[0]
        assert tool.data.python_code.storage_allowed_paths == []

    @pytest.mark.django_db
    def test_use_storage_false_tool_keeps_none(
        self, graph, task_node, surface_a, storage_file, py_tool
    ):
        SurfaceStorageItem.objects.create(
            surface=surface_a, storage_file=storage_file, can_view="allow"
        )
        SurfacePythonTool.objects.create(
            surface=surface_a, python_tool=py_tool, mode=ToolMode.ALLOW
        )
        task_node.surface_list.set([surface_a])
        wire_entrypoint(graph, task_node)

        graph_data = SessionManagerService()._build_graph_data(graph)

        task_data = graph_data.task_node_list[0]
        tool = task_data.tools[0]
        assert tool.data.python_code.storage_allowed_paths is None
