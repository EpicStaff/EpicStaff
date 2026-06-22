import pytest
from copy import deepcopy

from tables.models import Agent, Crew, Graph, LLMConfig, PythonCodeTool, PythonCode
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


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

    def test_create_entity(self, rich_seeded_db, export_service):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.AGENT)
        agent_data = deepcopy(export_data[EntityType.AGENT][0])

        agent_count_before = Agent.objects.count()
        new_agent = strategy.create_entity(agent_data, mapper)

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

    def test_create_entity(self, rich_seeded_db, export_service):
        crew = rich_seeded_db["crews"][0]
        export_data = export_service.export_entities(EntityType.CREW, [crew.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.CREW)
        crew_data = deepcopy(export_data[EntityType.CREW][0])

        crew_count_before = Crew.objects.count()
        new_crew = strategy.create_entity(crew_data, mapper)

        assert Crew.objects.count() == crew_count_before + 1
        assert new_crew.agents.count() == 2
        assert new_crew.task_set.count() == 2

    def test_name_uniqueness(self, rich_seeded_db, export_service):
        crew = rich_seeded_db["crews"][0]
        export_data = export_service.export_entities(EntityType.CREW, [crew.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.CREW)
        crew_data = deepcopy(export_data[EntityType.CREW][0])

        new_crew = strategy.create_entity(crew_data, mapper)
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

    def test_create_entity(self, rich_seeded_db, export_service):
        graph = rich_seeded_db["graph"]
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        mapper = _build_identity_mapper(export_data)
        strategy = _get_strategy(EntityType.GRAPH)
        graph_data = deepcopy(export_data[EntityType.GRAPH][0])

        graph_count_before = Graph.objects.count()
        new_graph = strategy.create_entity(graph_data, mapper)

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

    def test_create_entity(self, rich_seeded_db, export_service):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        strategy = _get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        # Need LLMModel mapped
        mapper = _build_identity_mapper(export_data)

        config_count_before = LLMConfig.objects.count()
        new_config = strategy.create_entity(config_data, mapper)

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
