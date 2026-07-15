"""
Round-trip import/export tests for the Surface and AgentDefinition strategies.
"""

import pytest

from tests.fixtures import *  # noqa: F401,F403

from tables.models import (
    Organization,
    AgentDefinition,
    AgentDefaultSurface,
    Surface,
    SurfacePythonTool,
    SurfaceMcpTool,
    SurfaceStorageItem,
    SurfaceKnowledge,
    McpTool,
    LLMConfig,
)
from tables.models.agent_models.surface_models import ToolMode
from tables.models.agent_models.agent_models import SurfacePlace
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.import_export.enums import EntityType
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.registry import entity_registry


@pytest.fixture
def export_service():
    return ExportService(entity_registry)


@pytest.fixture
def import_service():
    return ImportService(entity_registry)


@pytest.fixture
def default_org(db):
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def mcp_tool():
    return McpTool.objects.create(
        name="mcp_tool_1",
        transport="https://example.com/mcp",
        tool_name="search",
    )


@pytest.fixture
def surface_agent_seeded_db(rich_seeded_db, default_org, mcp_tool):
    """
    Builds an AgentDefinition owning one Surface (with a python + mcp tool row)
    plus a second, unowned Surface assigned to the agent as its default surface
    for the "flow" place.
    """
    agent_def = AgentDefinition.objects.create(
        organization=default_org,
        name="agent_def_1",
        description="description",
        instructions="instructions",
        llm_config=rich_seeded_db["llm_config"],
    )

    owned_surface = Surface.objects.create(
        organization=default_org,
        name="owned_surface_1",
        instructions="owned surface instructions",
        owner_agent=agent_def,
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface,
        python_tool=rich_seeded_db["python_code_tool"],
        mode=ToolMode.DENY,
    )
    SurfaceMcpTool.objects.create(
        surface=owned_surface,
        mcp_tool=mcp_tool,
        mode=ToolMode.ALLOW,
    )

    default_surface = Surface.objects.create(
        organization=default_org,
        name="default_surface_1",
        instructions="default surface instructions",
    )
    SurfacePythonTool.objects.create(
        surface=default_surface,
        python_tool=rich_seeded_db["python_code_tool"],
        mode=ToolMode.ALLOW,
    )

    AgentDefaultSurface.objects.create(
        agent_definition=agent_def,
        surface=default_surface,
        place=SurfacePlace.FLOW,
    )

    return {
        "agent_def": agent_def,
        "owned_surface": owned_surface,
        "default_surface": default_surface,
    }


@pytest.mark.django_db
class TestSurfaceRoundTrip:
    """
    Scenario 1 + 2: exporting a Surface pulls in its tool rows (with mode) but
    never its owner_agent; importing creates a brand-new, unowned Surface with
    the tool rows (and modes) recreated.
    """

    def test_export_import_roundtrip(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        owned_surface = surface_agent_seeded_db["owned_surface"]

        export_data = export_service.export_entities(
            EntityType.SURFACE, [owned_surface.id]
        )

        assert EntityType.AGENT_DEFINITION not in export_data

        surface_count_before = Surface.objects.count()
        agent_definition_count_before = AgentDefinition.objects.count()

        id_mapper, _ = import_service.import_data(export_data, EntityType.SURFACE)

        assert Surface.objects.count() == surface_count_before + 1
        assert AgentDefinition.objects.count() == agent_definition_count_before
        assert (
            id_mapper.has_mapping(EntityType.AGENT_DEFINITION, owned_surface.id)
            is False
        )
        assert id_mapper.get_new_ids(EntityType.AGENT_DEFINITION) == []

        new_surface_id = id_mapper.get_new_ids(EntityType.SURFACE)[0]
        new_surface = Surface.objects.get(id=new_surface_id)

        assert new_surface.id != owned_surface.id
        assert new_surface.owner_agent is None
        assert new_surface.organization_id == owned_surface.organization_id
        assert new_surface.instructions == owned_surface.instructions

    def test_surface_name_collision_renamed(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        owned_surface = surface_agent_seeded_db["owned_surface"]
        export_data = export_service.export_entities(
            EntityType.SURFACE, [owned_surface.id]
        )

        id_mapper, _ = import_service.import_data(export_data, EntityType.SURFACE)

        new_surface_id = id_mapper.get_new_ids(EntityType.SURFACE)[0]
        new_surface = Surface.objects.get(id=new_surface_id)

        assert new_surface.name == "owned_surface_1 (2)"

    def test_tools_and_modes_preserved(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        owned_surface = surface_agent_seeded_db["owned_surface"]
        export_data = export_service.export_entities(
            EntityType.SURFACE, [owned_surface.id]
        )

        id_mapper, _ = import_service.import_data(export_data, EntityType.SURFACE)

        new_surface_id = id_mapper.get_new_ids(EntityType.SURFACE)[0]
        new_surface = Surface.objects.get(id=new_surface_id)

        assert new_surface.python_tools.count() == owned_surface.python_tools.count()
        assert new_surface.mcp_tools.count() == owned_surface.mcp_tools.count()

        new_python_tool_row = new_surface.python_tools.get()
        assert new_python_tool_row.mode == ToolMode.DENY

        new_mcp_tool_row = new_surface.mcp_tools.get()
        assert new_mcp_tool_row.mode == ToolMode.ALLOW


@pytest.mark.django_db
class TestAgentDefinitionRoundTrip:
    """
    Scenario 3: exporting an AgentDefinition pulls in its llm configs and both
    its owned and default surfaces; importing creates a brand-new
    AgentDefinition, backfills ownership on the imported owned surface, and
    recreates the AgentDefaultSurface assignment. LLM configs are reused.
    """

    def test_export_import_roundtrip(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        agent_def = surface_agent_seeded_db["agent_def"]

        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_def.id]
        )

        agent_definition_count_before = AgentDefinition.objects.count()
        surface_count_before = Surface.objects.count()
        llm_config_count_before = LLMConfig.objects.count()

        id_mapper, _ = import_service.import_data(
            export_data, EntityType.AGENT_DEFINITION
        )

        assert AgentDefinition.objects.count() == agent_definition_count_before + 1
        assert Surface.objects.count() == surface_count_before + 2
        assert LLMConfig.objects.count() == llm_config_count_before

        new_agent_def_id = id_mapper.get_new_ids(EntityType.AGENT_DEFINITION)[0]
        new_agent_def = AgentDefinition.objects.get(id=new_agent_def_id)

        assert new_agent_def.id != agent_def.id
        assert new_agent_def.llm_config_id is not None

        assert id_mapper.has_mapping(EntityType.LLM_CONFIG, agent_def.llm_config_id)
        assert id_mapper.get_new_ids(EntityType.LLM_CONFIG) == [
            new_agent_def.llm_config_id
        ]

    def test_owned_surface_ownership_backfilled(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        agent_def = surface_agent_seeded_db["agent_def"]
        owned_surface = surface_agent_seeded_db["owned_surface"]

        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_def.id]
        )
        id_mapper, _ = import_service.import_data(
            export_data, EntityType.AGENT_DEFINITION
        )

        new_agent_def_id = id_mapper.get_new_ids(EntityType.AGENT_DEFINITION)[0]
        new_agent_def = AgentDefinition.objects.get(id=new_agent_def_id)

        assert id_mapper.has_mapping(EntityType.SURFACE, owned_surface.id)
        new_surface_ids = id_mapper.get_new_ids(EntityType.SURFACE)
        assert len(new_surface_ids) == 2

        new_owned_surface = new_agent_def.owned_surfaces.get()
        assert new_owned_surface.id in new_surface_ids
        assert new_owned_surface.owner_agent_id == new_agent_def.id

    def test_default_surface_assignment_recreated(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        agent_def = surface_agent_seeded_db["agent_def"]
        default_surface = surface_agent_seeded_db["default_surface"]

        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_def.id]
        )
        id_mapper, _ = import_service.import_data(
            export_data, EntityType.AGENT_DEFINITION
        )

        new_agent_def_id = id_mapper.get_new_ids(EntityType.AGENT_DEFINITION)[0]
        new_agent_def = AgentDefinition.objects.get(id=new_agent_def_id)

        assert id_mapper.has_mapping(EntityType.SURFACE, default_surface.id)

        default_surface_row = new_agent_def.default_surfaces.get()
        assert default_surface_row.place == SurfacePlace.FLOW
        assert default_surface_row.surface_id in id_mapper.get_new_ids(
            EntityType.SURFACE
        )


@pytest.mark.django_db
class TestNoStorageOrKnowledgeLeakage:
    """
    Scenario 4: neither Surface nor AgentDefinition import/export ever touches
    storage or knowledge relations.
    """

    def test_surface_import_does_not_create_storage_or_knowledge(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        owned_surface = surface_agent_seeded_db["owned_surface"]
        export_data = export_service.export_entities(
            EntityType.SURFACE, [owned_surface.id]
        )

        import_service.import_data(export_data, EntityType.SURFACE)

        assert SurfaceStorageItem.objects.count() == 0
        assert SurfaceKnowledge.objects.count() == 0

    def test_agent_definition_import_does_not_create_storage_or_knowledge(
        self, surface_agent_seeded_db, export_service, import_service
    ):
        agent_def = surface_agent_seeded_db["agent_def"]
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [agent_def.id]
        )

        import_service.import_data(export_data, EntityType.AGENT_DEFINITION)

        assert SurfaceStorageItem.objects.count() == 0
        assert SurfaceKnowledge.objects.count() == 0
