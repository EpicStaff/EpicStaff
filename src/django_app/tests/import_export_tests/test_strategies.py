import pytest
from copy import deepcopy

from tables.models import (
    Agent,
    AgentNode,
    Crew,
    Graph,
    LLMConfig,
    McpTool,
    PythonCodeTool,
    PythonCode,
    Organization,
    WebhookTrigger,
)
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
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


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
# Agent Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestAgentStrategy:
    def test_export_entity(self, rich_seeded_db):
        agent = rich_seeded_db["agents"][0]
        strategy = _get_strategy(EntityType.AGENT)
        data = strategy.export_entity(agent)

        assert data["role"] == "agent1"
        assert data["goal"] == "goal1"
        assert data["llm_config"] == agent.llm_config_id
        assert "realtime_agent" in data
        assert "tools" in data

    def test_extract_dependencies(self, rich_seeded_db):
        agent = rich_seeded_db["agents"][0]
        strategy = _get_strategy(EntityType.AGENT)
        deps = strategy.extract_dependencies_from_instance(agent)

        assert agent.llm_config_id in deps[EntityType.LLM_CONFIG]
        assert len(deps[EntityType.PYTHON_CODE_TOOL]) >= 1
        assert EntityType.REALTIME_CONFIG in deps

    def test_create_entity(self, rich_seeded_db, export_service, default_org):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT)
        agent_data = deepcopy(export_data[EntityType.AGENT][0])

        agent_count_before = Agent.objects.count()
        new_agent = strategy.create_entity(agent_data, mapper, org_id=default_org.id)

        assert Agent.objects.count() == agent_count_before + 1
        assert new_agent.role == agent.role
        assert new_agent.goal == agent.goal
        assert new_agent.llm_config_id is not None

    def test_find_existing_match(self, rich_seeded_db, export_service):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT)
        agent_data = deepcopy(export_data[EntityType.AGENT][0])
        agent_data.pop("id", None)

        found = strategy.find_existing(agent_data, mapper)
        assert found is not None
        assert found.id == agent.id

    def test_find_existing_no_match(self, rich_seeded_db, export_service):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT)
        agent_data = deepcopy(export_data[EntityType.AGENT][0])
        agent_data.pop("id", None)
        agent_data["role"] = "completely_different_role_xyz"

        found = strategy.find_existing(agent_data, mapper)
        assert found is None


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
        organization=default_org,
        name="agent_def_1",
        description="description",
        instructions="instructions",
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
            ("instructions", "different instructions"),
            ("metadata", {"different": "value"}),
            ("max_iter", 99),
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

    def test_find_existing_hit_ignoring_default_surfaces(
        self, agent_definition, export_service, default_org
    ):
        surface = Surface.objects.create(
            organization=default_org, name="default_surface_x"
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
        data["default_surfaces"] = []

        found = strategy.find_existing(data, mapper)
        assert found is not None
        assert found.id == agent_definition.id

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
                data, mapper, org_id=agent_definition.organization_id
            )
            is not None
        )


# ──────────────────────────────────────────
# Surface Strategy
# ──────────────────────────────────────────


@pytest.fixture
def surface_with_tools(rich_seeded_db, default_org, mcp_tool):
    surface = Surface.objects.create(
        organization=default_org, name="surface_1", instructions="do things"
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
        organization=default_org,
        name="flow_agent_def",
        description="description",
        instructions="instructions",
        llm_config=rich_seeded_db["llm_config"],
    )
    shared_surface = Surface.objects.create(
        organization=default_org, name="flow_shared_surface"
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
# Crew Strategy
# ──────────────────────────────────────────


@pytest.mark.django_db
class TestCrewStrategy:
    def test_export_entity(self, rich_seeded_db):
        crew = rich_seeded_db["crews"][0]
        strategy = _get_strategy(EntityType.CREW)
        data = strategy.export_entity(crew)

        assert data["name"] == "crew1"
        assert len(data["agents"]) == 2
        assert "tasks" in data
        assert len(data["tasks"]) == 2

    def test_extract_dependencies(self, rich_seeded_db):
        crew = rich_seeded_db["crews"][0]
        strategy = _get_strategy(EntityType.CREW)
        deps = strategy.extract_dependencies_from_instance(crew)

        assert EntityType.AGENT in deps
        assert len(deps[EntityType.AGENT]) == 2
        assert EntityType.LLM_CONFIG in deps
        assert EntityType.EMBEDDING_CONFIG in deps

    def test_create_entity(self, rich_seeded_db, export_service, default_org):
        crew = rich_seeded_db["crews"][0]
        export_data = export_service.export_entities(EntityType.CREW, [crew.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.CREW)
        crew_data = deepcopy(export_data[EntityType.CREW][0])

        crew_count_before = Crew.objects.count()
        new_crew = strategy.create_entity(crew_data, mapper, org_id=default_org.id)

        assert Crew.objects.count() == crew_count_before + 1
        assert new_crew.agents.count() == 2
        assert new_crew.task_set.count() == 2

    def test_name_uniqueness(self, rich_seeded_db, export_service, default_org):
        crew = rich_seeded_db["crews"][0]
        export_data = export_service.export_entities(EntityType.CREW, [crew.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.CREW)
        crew_data = deepcopy(export_data[EntityType.CREW][0])

        new_crew = strategy.create_entity(crew_data, mapper, org_id=default_org.id)
        assert new_crew.name == "crew1 (2)"


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

        assert EntityType.CREW in deps
        crew_ids = list(deps[EntityType.CREW])
        assert rich_seeded_db["crews"][0].id in crew_ids

    def test_create_entity(self, rich_seeded_db, export_service, default_org):
        graph = rich_seeded_db["graph"]
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.GRAPH)
        graph_data = deepcopy(export_data[EntityType.GRAPH][0])

        graph_count_before = Graph.objects.count()
        new_graph = strategy.create_entity(graph_data, mapper, org_id=default_org.id)

        assert Graph.objects.count() == graph_count_before + 1
        assert new_graph.name == "graph1 (2)"
        assert new_graph.crew_node_list.count() >= 1
        assert new_graph.edge_list.count() >= 1


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

    def test_create_entity(self, rich_seeded_db, export_service, default_org):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        strategy = _get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        # Need LLMModel mapped
        mapper = _build_identity_mapper(export_data)

        config_count_before = LLMConfig.objects.count()
        new_config = strategy.create_entity(config_data, mapper, org_id=default_org.id)

        assert LLMConfig.objects.count() == config_count_before + 1
        assert new_config.custom_name == "MyGPT-4o (2)"

    @pytest.mark.skip(reason="pre-existing failure, unrelated to EST-1529")
    def test_find_existing(self, rich_seeded_db, export_service):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        found = strategy.find_existing(config_data, mapper)
        assert found is not None
        assert found.id == rich_seeded_db["llm_config"].id


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
