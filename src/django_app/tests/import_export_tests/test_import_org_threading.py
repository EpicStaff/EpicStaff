import pytest

from tables.models import Agent, Graph
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

    def test_import_data_creates_agent_in_org(
        self, rich_seeded_db, export_service, default_org
    ):
        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        service = ImportService(entity_registry)
        id_mapper, _ = service.import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
        )

        new_agent_id = id_mapper.get_created_ids(EntityType.AGENT)[0]
        assert Agent.objects.get(id=new_agent_id).org_id == default_org.id
