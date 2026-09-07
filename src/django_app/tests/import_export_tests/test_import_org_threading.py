import pytest

from agents.models import AgentDefinition
from tables.models import Graph
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.schemas import ImportSettings


@pytest.mark.django_db
class TestImportOrgThreading:
    def test_import_data_stamps_org_on_graph(
        self, rich_seeded_db, export_service, default_org
    ):
        graph = rich_seeded_db["graph"]
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        service = ImportService(entity_registry)
        id_mapper, _ = service.import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
        )

        new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
        assert Graph.objects.get(id=new_graph_id).org_id == default_org.id

    def test_import_data_creates_agent_definition_in_org(
        self, exportable_agent_definition, export_service, default_org
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [exportable_agent_definition.id]
        )

        service = ImportService(entity_registry)
        id_mapper, _ = service.import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
        )

        new_definition_id = id_mapper.get_created_ids(EntityType.AGENT_DEFINITION)[0]
        assert (
            AgentDefinition.objects.get(id=new_definition_id).organization_id
            == default_org.id
        )
