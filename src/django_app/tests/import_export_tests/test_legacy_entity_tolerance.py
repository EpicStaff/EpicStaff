"""Old export files still contain CrewAI-era entity types ("Project", "Agent",
"CrewTag") and CrewNode entries in `nodes`. Those strategies are gone, but the
EntityType/NodeType enum members are deliberately kept so the files still parse.
Importing such a file must succeed with the unsupported parts skipped — never a
KeyError / 500.
"""

import pytest

from tables.models import CrewNode, Graph
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.schemas import ImportSettings


LEGACY_ENTITY_TYPES = (EntityType.CREW, EntityType.AGENT, EntityType.CREW_TAG)


@pytest.fixture
def legacy_export_data():
    """A minimal pre-CrewAI-removal flow export: one graph whose only node is a
    CrewNode, plus the crew/agent/tag entities that used to back it."""
    return {
        "main_entity": EntityType.GRAPH,
        EntityType.CREW_TAG: [{"id": 1, "name": "legacy tag"}],
        EntityType.AGENT: [{"id": 2, "role": "r", "goal": "g", "backstory": "b"}],
        EntityType.CREW: [{"id": 3, "name": "legacy crew", "agents": [2]}],
        EntityType.GRAPH: [
            {
                "id": 4,
                "name": "legacy flow",
                "description": "",
                "metadata": {"nodes": [], "edges": []},
                "nodes": [
                    {
                        "id": 5,
                        "node_type": NodeType.CREW_NODE,
                        "node_name": "legacy crew node",
                        "crew": 3,
                        "metadata": {},
                    }
                ],
                "edge_list": [],
                "conditional_edge_list": [],
            }
        ],
    }


@pytest.mark.django_db
def test_legacy_entities_are_skipped_not_raised(legacy_export_data, default_org):
    id_mapper, _ = ImportService(entity_registry).import_data(
        legacy_export_data,
        EntityType.GRAPH,
        settings=ImportSettings(),
        org_id=default_org.id,
    )

    new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    new_graph = Graph.objects.get(id=new_graph_id)

    assert new_graph.name == "legacy flow"
    assert new_graph.org_id == default_org.id
    # The CrewNode entry is skipped, and no legacy entity is mapped/created.
    assert not CrewNode.objects.filter(graph=new_graph).exists()

    for entity_type in LEGACY_ENTITY_TYPES:
        assert id_mapper.get_created_ids(entity_type) == []


@pytest.mark.django_db
def test_registry_reports_legacy_types_as_unsupported():
    for entity_type in LEGACY_ENTITY_TYPES:
        assert entity_registry.has_strategy(entity_type) is False

    assert entity_registry.has_strategy(EntityType.CREW_NODE) is False
    assert entity_registry.has_strategy(EntityType.GRAPH) is True
