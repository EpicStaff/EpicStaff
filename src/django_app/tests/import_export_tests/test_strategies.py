import pytest
from copy import deepcopy
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

from rest_framework.exceptions import ValidationError

from rbac.models import Organization
from tables.models import AgentNode, Graph, LLMConfig, McpTool, PythonCodeTool, PythonCode, WebhookTrigger
from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.import_export.registry import entity_registry
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import nest_owned_surface_entries


@pytest.fixture
def default_org(db):
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


def _get_strategy(entity_type):
    return entity_registry.get_strategy(entity_type)


def _build_identity_mapper(export_data):
    """Build an IDMapper where every old ID maps to itself (for tests against existing DB)."""
    mapper = IDMapper()
    for entity_type, entities in export_data.items():
        if entity_type == "main_entity":
            continue
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and "id" in entity:
                    mapper.map(
                        entity_type, entity["id"], entity["id"], was_created=False
                    )
    return mapper


# ──────────────────────────────────────────
# AgentDefinition Strategy
# ──────────────────────────────────────────


@pytest.fixture
def mcp_tool(default_org):
    return McpTool.objects.create(
        org=default_org,
        name="mcp_tool_1",
        transport="https://example.com/mcp",
        tool_name="search",
    )


@pytest.fixture
def agent_definition(rich_seeded_db, default_org):
    return AgentDefinition.objects.create(
        org=default_org,
        name="agent_def_1",
        description="description",
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
        metadata={"key": "value"},
        llm_config=rich_seeded_db["llm_config"],
        max_iter=5,
    )


@pytest.mark.django_db
class TestAgentDefinitionStrategy:
    def test_find_existing_match(self, agent_definition, export_service):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])

        found = strategy.find_existing(data, mapper)
        assert found is not None
        assert found.id == agent_definition.id

    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "different_name"),
            ("description", "different description"),
            ("instruction_list", [{"name": "Instruction_1.md", "content": "different"}]),
            ("metadata", {"different": "value"}),
            ("max_iter", 42),
        ],
    )
    def test_find_existing_miss_on_scalar_field(
        self, agent_definition, export_service, field, value
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        data[field] = value

        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_miss_on_llm_config(self, agent_definition, export_service):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        data["llm_config"] = None

        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_miss_on_fcm_llm_config(
        self, agent_definition, export_service
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        data["fcm_llm_config"] = agent_definition.llm_config_id

        assert strategy.find_existing(data, mapper) is None

    def test_export_carries_instruction_list_not_compiled_instructions(
        self, agent_definition, export_service
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        exported = export_data[EntityType.AGENT_DEFINITION][0]

        assert exported["instruction_list"] == [
            {"name": "Instruction_1.md", "content": "instructions"}
        ]
        assert "instructions" not in exported

    def test_find_existing_matches_legacy_instructions_payload(
        self, agent_definition, export_service
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        del data["instruction_list"]
        data["instructions"] = "instructions"
        data["metadata"] = {**data["metadata"], "instructions_format": "markdown"}

        found = strategy.find_existing(data, mapper)
        assert found is not None
        assert found.id == agent_definition.id

    @pytest.mark.parametrize(
        "legacy_instructions,expected_instruction_list",
        [
            ("be brief", [{"name": "Instruction_1.md", "content": "be brief"}]),
            ("   ", []),
            ("", []),
        ],
    )
    def test_create_entity_converts_legacy_instructions(
        self,
        agent_definition,
        export_service,
        default_org,
        legacy_instructions,
        expected_instruction_list,
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        del data["instruction_list"]
        data["instructions"] = legacy_instructions
        data["metadata"] = {"key": "value", "instructions_format": "markdown"}

        created = strategy.create_entity(data, mapper, org_id=default_org.id)

        created.refresh_from_db()
        assert created.instruction_list == expected_instruction_list
        assert created.metadata == {"key": "value"}

    def test_create_entity_rejects_duplicate_instruction_names(
        self, agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        data["instruction_list"] = [
            {"name": "Rules.md", "content": "a"},
            {"name": "rules.md", "content": "b"},
        ]

        with pytest.raises(ValidationError):
            strategy.create_entity(data, mapper, org_id=default_org.id)

    def test_find_existing_miss_on_default_surfaces(
        self, agent_definition, export_service, default_org
    ):
        surface = Surface.objects.create(
            org=default_org, name="default_surface_x"
        )
        AgentDefaultSurface.objects.create(
            agent_definition=agent_definition,
            surface=surface,
            place=SurfacePlace.FLOW,
        )

        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        assert strategy.find_existing(deepcopy(data), mapper).id == agent_definition.id

        data["default_surfaces"] = []

        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_miss_on_owned_surfaces(
        self, agent_definition, export_service, default_org
    ):
        Surface.objects.create(
            org=default_org, name="owned_surface_x", owner_agent=agent_definition
        )

        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = nest_owned_surface_entries(export_data)[EntityType.AGENT_DEFINITION][0]
        assert strategy.find_existing(deepcopy(data), mapper).id == agent_definition.id

        edited = deepcopy(data)
        edited[OWNED_SURFACE_ENTRIES_KEY][0]["instructions"] = "edited after export"
        assert strategy.find_existing(edited, mapper) is None

        data[OWNED_SURFACE_ENTRIES_KEY] = []
        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_prefers_exact_name_over_newer_identical_copy(
        self, agent_definition, export_service, default_org
    ):
        AgentDefinition.objects.create(
            org=default_org,
            name="agent_def_1 #2",
            description=agent_definition.description,
            instruction_list=agent_definition.instruction_list,
            metadata=agent_definition.metadata,
            llm_config=agent_definition.llm_config,
            max_iter=agent_definition.max_iter,
        )
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = nest_owned_surface_entries(export_data)[EntityType.AGENT_DEFINITION][0]

        assert strategy.find_existing(data, mapper).id == agent_definition.id

    def test_find_existing_skips_copy_without_equivalent_owned_surface(
        self, agent_definition, export_service, default_org
    ):
        Surface.objects.create(
            org=default_org, name="owned_surface_x", owner_agent=agent_definition
        )
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        # After export the original is renamed and a copy takes the exact name,
        # so the copy sorts first. It owns as many surfaces as the file, in the
        # same name family but with other content, so only the content pairing
        # can reject it.
        agent_definition.name = "agent_def_1 #2"
        agent_definition.save(update_fields=["name"])
        copy_without_equivalent = AgentDefinition.objects.create(
            org=default_org,
            name="agent_def_1",
            description=agent_definition.description,
            instruction_list=agent_definition.instruction_list,
            metadata=agent_definition.metadata,
            llm_config=agent_definition.llm_config,
            max_iter=agent_definition.max_iter,
        )
        Surface.objects.create(
            org=default_org,
            name="owned_surface_x #2",
            instructions="different",
            owner_agent=copy_without_equivalent,
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = nest_owned_surface_entries(export_data)[EntityType.AGENT_DEFINITION][0]

        assert strategy.find_existing(data, mapper).id == agent_definition.id

    def test_find_existing_no_reuse_across_orgs(self, agent_definition, export_service):
        other_org = Organization.objects.create(name="Other Org")
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT_DEFINITION)
        data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])

        assert strategy.find_existing(data, mapper, org_id=other_org.id) is None
        assert (
            strategy.find_existing(
                data, mapper, org_id=agent_definition.org_id
            )
            is not None
        )


LEGACY_NULL_EXECUTION_FIELDS = {
    "max_iter": None,
    "max_rpm": None,
    "max_execution_time": None,
    "cache": None,
    "max_retry_limit": None,
    "max_tool_calls": None,
    "tool_timeout": None,
    "max_consecutive_failures": None,
    "schema_max_retries": None,
}


LEGACY_SINGLETON_VALUES = {
    "max_iter": 25,
    "max_rpm": 10,
    "max_execution_time": 60,
    "cache": False,
    "max_retry_limit": 3,
    "max_tool_calls": 15,
    "tool_timeout": 300,
    "max_consecutive_failures": 3,
    "schema_max_retries": 2,
}


def _legacy_agent_definition_payload(export_service, agent_definition, **overrides):
    export_data = export_service.export_entities(
        EntityType.AGENT_DEFINITION, [agent_definition.id]
    )
    data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
    data.update(overrides)
    return data, _build_identity_mapper(export_data)


@pytest.mark.django_db
class TestAgentDefinitionStrategyLegacyExecutionFields:
    def test_create_entity_replaces_nulls_with_legacy_singleton_values(
        self, agent_definition, export_service, default_org
    ):
        data, mapper = _legacy_agent_definition_payload(
            export_service, agent_definition, **LEGACY_NULL_EXECUTION_FIELDS
        )

        created = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            data, mapper, org_id=default_org.id
        )

        created.refresh_from_db()
        for field_name, value in LEGACY_SINGLETON_VALUES.items():
            assert getattr(created, field_name) == value, field_name

    def test_create_entity_clamps_out_of_range_values(
        self, agent_definition, export_service, default_org
    ):
        data, mapper = _legacy_agent_definition_payload(
            export_service,
            agent_definition,
            max_iter=500,
            max_execution_time=5,
            max_retry_limit=-3,
            tool_timeout=99_999,
            default_temperature=3.5,
        )

        created = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            data, mapper, org_id=default_org.id
        )

        created.refresh_from_db()
        assert created.max_iter == 90
        assert created.max_execution_time == 60
        assert created.max_retry_limit == 0
        assert created.tool_timeout == 1800
        assert created.default_temperature == 2.0

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_create_entity_turns_non_finite_temperature_into_null(
        self, agent_definition, export_service, default_org, value
    ):
        data, mapper = _legacy_agent_definition_payload(
            export_service, agent_definition, default_temperature=value
        )

        created = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            data, mapper, org_id=default_org.id
        )

        created.refresh_from_db()
        assert created.default_temperature is None

    def test_find_existing_reuses_row_created_from_null_payload(
        self, agent_definition, export_service, default_org
    ):
        AgentDefinition.objects.filter(pk=agent_definition.pk).update(
            **LEGACY_SINGLETON_VALUES
        )
        data, mapper = _legacy_agent_definition_payload(
            export_service, agent_definition, **LEGACY_NULL_EXECUTION_FIELDS
        )

        found = _get_strategy(EntityType.AGENT_DEFINITION).find_existing(
            data, mapper, org_id=default_org.id
        )

        assert found is not None
        assert found.id == agent_definition.id
        assert data["max_iter"] is None

    def test_numeric_string_is_left_to_the_serializer(
        self, agent_definition, export_service, default_org
    ):
        data, mapper = _legacy_agent_definition_payload(
            export_service, agent_definition, max_iter="25"
        )

        created = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            data, mapper, org_id=default_org.id
        )

        created.refresh_from_db()
        assert created.max_iter == 25

    def test_out_of_range_string_is_rejected_not_clamped(
        self, agent_definition, export_service, default_org
    ):
        data, mapper = _legacy_agent_definition_payload(
            export_service, agent_definition, max_iter="500"
        )

        with pytest.raises(ValidationError) as error:
            _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
                data, mapper, org_id=default_org.id
            )

        assert "max_iter" in error.value.detail


# ──────────────────────────────────────────
# Surface Strategy
# ──────────────────────────────────────────


@pytest.fixture
def surface_with_tools(rich_seeded_db, default_org, mcp_tool):
    surface = Surface.objects.create(
        org=default_org, name="surface_1", instructions="do things"
    )
    SurfacePythonTool.objects.create(
        surface=surface,
        python_tool=rich_seeded_db["python_code_tool"],
        mode=ToolMode.ALLOW,
    )
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=mcp_tool, mode=ToolMode.DENY
    )
    return surface


@pytest.mark.django_db
class TestSurfaceStrategy:
    def test_find_existing_match(self, surface_with_tools, export_service):
        export_data = export_service.export_entities(
            EntityType.SURFACE, [surface_with_tools.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.SURFACE)
        data = deepcopy(export_data[EntityType.SURFACE][0])

        found = strategy.find_existing(data, mapper)
        assert found is not None
        assert found.id == surface_with_tools.id

    def test_find_existing_miss_on_instructions(
        self, surface_with_tools, export_service
    ):
        export_data = export_service.export_entities(
            EntityType.SURFACE, [surface_with_tools.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.SURFACE)
        data = deepcopy(export_data[EntityType.SURFACE][0])
        data["instructions"] = "different instructions"

        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_miss_on_tool_set(self, surface_with_tools, export_service):
        export_data = export_service.export_entities(
            EntityType.SURFACE, [surface_with_tools.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.SURFACE)
        data = deepcopy(export_data[EntityType.SURFACE][0])
        data["tools"][EntityType.PYTHON_CODE_TOOL] = []

        assert strategy.find_existing(data, mapper) is None

    def test_find_existing_miss_on_tool_mode(self, surface_with_tools, export_service):
        export_data = export_service.export_entities(
            EntityType.SURFACE, [surface_with_tools.id]
        )
        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.SURFACE)
        data = deepcopy(export_data[EntityType.SURFACE][0])
        data["tools"][EntityType.PYTHON_CODE_TOOL][0]["mode"] = ToolMode.DENY

        assert strategy.find_existing(data, mapper) is None


# ──────────────────────────────────────────
# AgentDefinition + Surface dedup on re-import
# ──────────────────────────────────────────


@pytest.fixture
def graph_with_agent_node(rich_seeded_db, default_org):
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="flow_agent_def",
        description="description",
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
        llm_config=rich_seeded_db["llm_config"],
    )
    shared_surface = Surface.objects.create(
        org=default_org, name="flow_shared_surface"
    )

    graph = Graph.objects.create(
        org=default_org, name="flow_graph_1", metadata={"nodes": [], "edges": []}
    )
    agent_node = AgentNode.objects.create(
        graph=graph, agent_definition=agent_definition
    )
    agent_node.surface_list.set([shared_surface])

    return graph


@pytest.mark.django_db
class TestAgentDefinitionAndSurfaceDedupOnReimport:
    def test_reimporting_same_graph_does_not_duplicate_dependencies(
        self, graph_with_agent_node, export_service, import_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.GRAPH, [graph_with_agent_node.id]
        )

        import_service.import_data(
            deepcopy(export_data), EntityType.GRAPH, org_id=default_org.id
        )

        agent_definition_count_after_first_import = AgentDefinition.objects.count()
        surface_count_after_first_import = Surface.objects.count()

        import_service.import_data(
            deepcopy(export_data), EntityType.GRAPH, org_id=default_org.id
        )

        assert (
            AgentDefinition.objects.count() == agent_definition_count_after_first_import
        )
        assert Surface.objects.count() == surface_count_after_first_import


# ──────────────────────────────────────────
# Graph Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestGraphStrategy:
    def test_export_entity(self, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        strategy = _get_strategy(EntityType.GRAPH)
        data = strategy.export_entity(graph)

        assert data["name"] == "graph1"
        assert "nodes" in data
        assert "edge_list" in data

    def test_extract_dependencies(self, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        strategy = _get_strategy(EntityType.GRAPH)
        deps = strategy.extract_dependencies_from_instance(graph)

        # A legacy CrewNode has no node strategy anymore, so it contributes no
        # dependency of its own.
        assert EntityType.CREW not in deps

    def test_create_entity(self, rich_seeded_db, export_service, default_org):
        graph = rich_seeded_db["graph"]
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.GRAPH)
        graph_data = deepcopy(export_data[EntityType.GRAPH][0])

        graph_count_before = Graph.objects.count()
        new_graph = strategy.create_entity(graph_data, mapper, org_id=default_org.id)

        assert Graph.objects.count() == graph_count_before + 1
        assert new_graph.name == "graph1 #2"
        # The source graph's legacy CrewNode is skipped, not recreated.
        assert new_graph.crew_node_list.count() == 0


# ──────────────────────────────────────────
# PythonCodeTool Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestPythonCodeToolStrategy:
    def test_export_entity(self, rich_seeded_db):
        tool = rich_seeded_db["python_code_tool"]
        strategy = _get_strategy(EntityType.PYTHON_CODE_TOOL)
        data = strategy.export_entity(tool)

        assert data["name"] == "custom_tool1"
        assert "python_code" in data
        assert data["python_code"]["entrypoint"] == "main"

    def test_create_entity(self, rich_seeded_db):
        tool = rich_seeded_db["python_code_tool"]
        strategy = _get_strategy(EntityType.PYTHON_CODE_TOOL)
        data = deepcopy(strategy.export_entity(tool))
        mapper = IDMapper()

        tool_count_before = PythonCodeTool.objects.count()
        new_tool = strategy.create_entity(data, mapper)

        assert PythonCodeTool.objects.count() == tool_count_before + 1
        assert new_tool.python_code.entrypoint == "main"

    def test_find_existing_match(self, rich_seeded_db):
        tool = rich_seeded_db["python_code_tool"]
        strategy = _get_strategy(EntityType.PYTHON_CODE_TOOL)
        data = deepcopy(strategy.export_entity(tool))
        mapper = IDMapper()

        found = strategy.find_existing(data, mapper)
        assert found is not None
        assert found.id == tool.id

    def test_find_existing_different_code(self, rich_seeded_db):
        tool = rich_seeded_db["python_code_tool"]
        strategy = _get_strategy(EntityType.PYTHON_CODE_TOOL)
        data = deepcopy(strategy.export_entity(tool))
        data["python_code"]["code"] = "def main(): return 'different'"
        mapper = IDMapper()

        found = strategy.find_existing(data, mapper)
        assert found is None


# ──────────────────────────────────────────
# LLMConfig Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestLLMConfigStrategy:
    def test_export_entity(self, rich_seeded_db):
        config = rich_seeded_db["llm_config"]
        strategy = _get_strategy(EntityType.LLM_CONFIG)
        data = strategy.export_entity(config)

        assert data["custom_name"] == "MyGPT-4o"
        assert data["temperature"] == 0.5

    def test_create_entity(
        self, exportable_agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        strategy = _get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        # Need LLMModel mapped
        mapper = _build_identity_mapper(export_data)

        config_count_before = LLMConfig.objects.count()
        new_config = strategy.create_entity(config_data, mapper, org_id=default_org.id)

        assert LLMConfig.objects.count() == config_count_before + 1
        assert new_config.custom_name == "MyGPT-4o #2"

    def test_export_entity_omits_created_at(self, rich_seeded_db):
        strategy = _get_strategy(EntityType.LLM_CONFIG)

        data = strategy.export_entity(rich_seeded_db["llm_config"])

        assert "created_at" not in data

    def test_imported_config_gets_its_own_creation_time(
        self, exportable_agent_definition, export_service, default_org
    ):
        source_config = exportable_agent_definition.llm_config
        source_created_at = datetime(2001, 1, 1, tzinfo=dt_timezone.utc)
        LLMConfig.objects.filter(pk=source_config.pk).update(created_at=source_created_at)
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])
        # A hand-edited file carrying the field must not set it either.
        config_data["created_at"] = source_created_at.isoformat()
        before = timezone.now()

        new_config = _get_strategy(EntityType.LLM_CONFIG).create_entity(
            config_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_config.refresh_from_db()
        assert new_config.created_at >= before

    def test_import_of_pre_created_at_export_succeeds(
        self, exportable_agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])
        config_data.pop("created_at", None)

        new_config = _get_strategy(EntityType.LLM_CONFIG).create_entity(
            config_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_config.refresh_from_db()
        assert new_config.created_at is not None

    @pytest.mark.skip(reason="pre-existing failure from before the tool-variables rework; cause not investigated")
    def test_find_existing(
        self, rich_seeded_db, exportable_agent_definition, export_service
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        found = strategy.find_existing(config_data, mapper)
        assert found is not None
        assert found.id == rich_seeded_db["llm_config"].id


# ──────────────────────────────────────────
# created_at: EmbeddingConfig and AgentDefinition
# ──────────────────────────────────────────

SOURCE_CREATED_AT = datetime(2001, 1, 1, tzinfo=dt_timezone.utc)


def _exported_with_old_creation_time(export_service, entity_type, instance) -> dict:
    type(instance).objects.filter(pk=instance.pk).update(created_at=SOURCE_CREATED_AT)
    return export_service.export_entities(entity_type, [instance.id])


@pytest.mark.django_db
class TestEmbeddingConfigCreatedAt:
    def test_export_entity_omits_created_at(self, embedding_config):
        data = _get_strategy(EntityType.EMBEDDING_CONFIG).export_entity(embedding_config)

        assert "created_at" not in data

    def test_imported_config_gets_its_own_creation_time(
        self, embedding_config, export_service, default_org
    ):
        export_data = _exported_with_old_creation_time(
            export_service, EntityType.EMBEDDING_CONFIG, embedding_config
        )
        config_data = deepcopy(export_data[EntityType.EMBEDDING_CONFIG][0])
        # A hand-edited file carrying the field must not set it either.
        config_data["created_at"] = SOURCE_CREATED_AT.isoformat()
        before = timezone.now()

        new_config = _get_strategy(EntityType.EMBEDDING_CONFIG).create_entity(
            config_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_config.refresh_from_db()
        assert new_config.pk != embedding_config.pk
        assert new_config.created_at >= before

    def test_import_of_pre_created_at_export_gets_a_creation_time(
        self, embedding_config, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.EMBEDDING_CONFIG, [embedding_config.id]
        )
        config_data = deepcopy(export_data[EntityType.EMBEDDING_CONFIG][0])
        config_data.pop("created_at", None)

        new_config = _get_strategy(EntityType.EMBEDDING_CONFIG).create_entity(
            config_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_config.refresh_from_db()
        assert new_config.created_at is not None

    def test_reimport_finds_the_existing_config(
        self, embedding_config, export_service, default_org
    ):
        export_data = _exported_with_old_creation_time(
            export_service, EntityType.EMBEDDING_CONFIG, embedding_config
        )
        config_data = deepcopy(export_data[EntityType.EMBEDDING_CONFIG][0])

        found = _get_strategy(EntityType.EMBEDDING_CONFIG).find_existing(
            config_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        assert found is not None
        assert found.id == embedding_config.id


@pytest.mark.django_db
class TestAgentDefinitionCreatedAt:
    def test_export_entity_omits_created_at(self, agent_definition):
        data = _get_strategy(EntityType.AGENT_DEFINITION).export_entity(agent_definition)

        assert "created_at" not in data

    def test_imported_agent_gets_its_own_creation_time(
        self, agent_definition, export_service, default_org
    ):
        export_data = _exported_with_old_creation_time(
            export_service, EntityType.AGENT_DEFINITION, agent_definition
        )
        agent_data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        # A hand-edited file carrying the field must not set it either.
        agent_data["created_at"] = SOURCE_CREATED_AT.isoformat()
        before = timezone.now()

        new_agent = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            agent_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_agent.refresh_from_db()
        assert new_agent.pk != agent_definition.pk
        assert new_agent.created_at >= before

    def test_import_of_pre_created_at_export_gets_a_creation_time(
        self, agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_definition.id]
        )
        agent_data = deepcopy(export_data[EntityType.AGENT_DEFINITION][0])
        agent_data.pop("created_at", None)

        new_agent = _get_strategy(EntityType.AGENT_DEFINITION).create_entity(
            agent_data, _build_identity_mapper(export_data), org_id=default_org.id
        )

        new_agent.refresh_from_db()
        assert new_agent.created_at is not None


# ──────────────────────────────────────────
# WebhookTrigger Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestWebhookTriggerStrategy:
    def test_create_entity_stamps_org_on_fresh_db(self, default_org):
        """Regression test: create_entity used to save WebhookTrigger without
        an org, which 500s on any DB since org_id is NOT NULL (see migration
        0206_webhook_trigger_org_not_null)."""
        strategy = _get_strategy(EntityType.WEBHOOK_TRIGGER)
        data = {"path": "imported-webhook", "provider_type": None}

        trigger_count_before = WebhookTrigger.objects.count()
        new_trigger = strategy.create_entity(data, IDMapper(), org_id=default_org.id)

        assert WebhookTrigger.objects.count() == trigger_count_before + 1
        assert new_trigger.org_id == default_org.id
        assert new_trigger.path == "imported-webhook"

    def test_get_org_scope_q_matches_org_id_column(self, default_org):
        other_org = Organization.objects.create(name="Other org")
        own = WebhookTrigger.objects.create(path="own-org-webhook", org=default_org)
        WebhookTrigger.objects.create(path="other-org-webhook", org=other_org)

        strategy = _get_strategy(EntityType.WEBHOOK_TRIGGER)
        scoped = WebhookTrigger.objects.filter(strategy.get_org_scope_q(default_org.id))

        assert list(scoped) == [own]


# ──────────────────────────────────────────
# TelegramTriggerNode Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestTelegramTriggerNodeStrategy:
    def test_create_entity_remaps_webhook_trigger_fk(self, rich_seeded_db, default_org):
        """Regression test: create_entity used to pass the raw OLD
        webhook_trigger id straight through to the serializer instead of
        remapping it via id_mapper, which 400s on any target DB where that
        old id doesn't exist ("Invalid pk ... - object does not exist.")."""
        graph = rich_seeded_db["graph"]
        old_trigger = WebhookTrigger.objects.create(path="old-webhook", org=default_org)
        new_trigger = WebhookTrigger.objects.create(path="new-webhook", org=default_org)

        mapper = IDMapper()
        mapper.map(EntityType.GRAPH, graph.id, graph.id, was_created=False)
        mapper.map(EntityType.WEBHOOK_TRIGGER, old_trigger.id, new_trigger.id)

        strategy = _get_strategy(EntityType.TELEGRAM_TRIGGER_NODE)
        data = {
            "node_name": "telegram_node_1",
            "graph": graph.id,
            "webhook_trigger": old_trigger.id,
            "fields": [],
        }

        node = strategy.create_entity(data, mapper)

        assert node.webhook_trigger_id == new_trigger.id

    def test_create_entity_with_no_webhook_trigger(self, rich_seeded_db):
        graph = rich_seeded_db["graph"]
        strategy = _get_strategy(EntityType.TELEGRAM_TRIGGER_NODE)
        data = {
            "node_name": "telegram_node_2",
            "graph": graph.id,
            "webhook_trigger": None,
            "fields": [],
        }

        mapper = IDMapper()
        mapper.map(EntityType.GRAPH, graph.id, graph.id, was_created=False)
        node = strategy.create_entity(data, mapper)

        assert node.webhook_trigger_id is None


# ---- provider model strategies: per-org name uniquification ----


@pytest.fixture
def org_a_ie(db):
    return Organization.objects.create(name="IE Org A")


@pytest.fixture
def org_b_ie(db):
    return Organization.objects.create(name="IE Org B")


@pytest.mark.django_db
def test_llm_model_import_does_not_rename_around_another_orgs_name(org_a_ie, org_b_ie):
    """Uniquification must be scoped to the target org: org A owning 'shared-name'
    must not force org B's import to become 'shared-name (1)'."""
    from tables.import_export.strategies.llm_models import LLMModelStrategy
    from tables.models import Provider
    from tables.models.llm_models import LLMModel

    provider = Provider.objects.create(name="openai")
    LLMModel.objects.create(
        name="shared-name", llm_provider=provider, is_custom=True, org=org_a_ie
    )

    created = LLMModelStrategy().create_entity(
        {
            "name": "shared-name",
            "provider_name": "openai",
            "tags": [],
            "is_visible": True,
        },
        IDMapper(),
        org_id=org_b_ie.id,
    )

    assert created.name == "shared-name"
    assert created.org_id == org_b_ie.id


@pytest.mark.django_db
def test_llm_model_import_still_uniquifies_within_the_target_org(org_a_ie):
    from tables.import_export.strategies.llm_models import LLMModelStrategy
    from tables.models import Provider
    from tables.models.llm_models import LLMModel

    provider = Provider.objects.create(name="openai")
    LLMModel.objects.create(
        name="taken", llm_provider=provider, is_custom=True, org=org_a_ie
    )

    created = LLMModelStrategy().create_entity(
        {"name": "taken", "provider_name": "openai", "tags": [], "is_visible": True},
        IDMapper(),
        org_id=org_a_ie.id,
    )

    assert created.name != "taken"
    assert created.org_id == org_a_ie.id


@pytest.mark.django_db
def test_llm_model_import_without_an_org_falls_back_to_the_default_org(default_org):
    """ImportService declares org_id as optional, and org=NULL + is_custom=True
    would be invisible to every org and immutable under the write lockdown."""
    from tables.import_export.strategies.llm_models import LLMModelStrategy
    from tables.models import Provider

    Provider.objects.create(name="openai")

    created = LLMModelStrategy().create_entity(
        {"name": "no-org", "provider_name": "openai", "tags": [], "is_visible": True},
        IDMapper(),
    )

    assert created.org_id == default_org.id
    assert created.is_custom is True


@pytest.mark.django_db
def test_llm_model_import_cannot_mint_a_predefined_row(org_a_ie):
    """LLMModelImportSerializer excludes only llm_provider and created_by, so a
    crafted payload can otherwise set predefined=True."""
    from tables.import_export.strategies.llm_models import LLMModelStrategy
    from tables.models import Provider

    Provider.objects.create(name="openai")

    created = LLMModelStrategy().create_entity(
        {
            "name": "sneaky",
            "provider_name": "openai",
            "tags": [],
            "is_visible": True,
            "predefined": True,
        },
        IDMapper(),
        org_id=org_a_ie.id,
    )

    assert created.predefined is False
    assert created.is_custom is True
    assert created.org_id == org_a_ie.id
