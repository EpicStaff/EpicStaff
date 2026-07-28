"""
Tests for two import fixes:
  1. Imported LLMConfig must not inherit api_key from an existing config.
  2. Imported Graph must get a GraphOrganization row pointing at the default org.
"""

import pytest
from copy import deepcopy

from tests.fixtures import *  # noqa: F401,F403

from tables.models import (
    LLMConfig,
    Graph,
    Organization,
    GraphOrganization,
)
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.registry import entity_registry
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


@pytest.fixture
def export_service():
    return ExportService(entity_registry)


@pytest.fixture
def import_service():
    return ImportService(entity_registry)


@pytest.fixture
def default_org(db):
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


def _build_identity_mapper(export_data):
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


@pytest.mark.django_db
class TestImportedLLMConfigApiKeyNotLeaked:
    def test_create_entity_does_not_copy_api_key_from_existing_config(
        self, rich_seeded_db, export_service
    ):
        """
        Another LLMConfig with a non-null api_key for the same provider exists in DB.
        Calling create_entity must produce a config with api_key=None — no leaking.
        """
        existing_config = rich_seeded_db["llm_config"]
        existing_config.api_key = "sk-leaked-key-must-not-appear-on-import"
        existing_config.save()

        agent = rich_seeded_db["agents"][0]
        export_data = export_service.export_entities(EntityType.AGENT, [agent.id])

        mapper = _build_identity_mapper(export_data)
        strategy = entity_registry.get_strategy(EntityType.LLM_CONFIG)
        config_data = deepcopy(export_data[EntityType.LLM_CONFIG][0])

        new_config = strategy.create_entity(config_data, mapper)

        assert (
            new_config.api_key is None
        ), f"api_key={new_config.api_key!r} was copied from existing config; expected None"


@pytest.mark.django_db
class TestImportedGraphHasOrganizationStamped:
    def test_imported_graph_gets_default_org(
        self, rich_seeded_db, export_service, import_service, default_org
    ):
        """
        Importing a graph bundle must stamp a GraphOrganization row on every
        imported graph pointing at the default organization.
        """
        graph = rich_seeded_db["graph"]
        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_graph_ids = id_mapper.get_new_ids(EntityType.GRAPH)
        assert new_graph_ids, "Expected at least one new Graph to be created"

        for graph_id in new_graph_ids:
            imported_graph = Graph.objects.get(id=graph_id)
            assert GraphOrganization.objects.filter(
                graph=imported_graph,
            ).exists(), (
                f"Graph {graph_id} ({imported_graph.name!r}) has no GraphOrganization "
                f"for the default org"
            )
            # Org is derived from graph.org now, so assert ownership via the graph.
            assert (
                imported_graph.org == default_org
            ), f"Graph {graph_id} ({imported_graph.name!r}) is not owned by the default org"
