import pytest

from tables.models import Graph, StartNode
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry

ORPHAN_SUBGRAPH_ID = 999_999_999


@pytest.mark.django_db
class TestGraphMetadataOrphanSubgraphReference:
    def test_import_succeeds_and_keeps_orphan_subgraph_node_with_stale_id(
        self, export_service, import_service, default_org
    ):
        assert not Graph.objects.filter(id=ORPHAN_SUBGRAPH_ID).exists()

        graph = Graph.objects.create(
            name="graph_with_orphan_subgraph_reference",
            metadata={
                "nodes": [
                    {
                        "type": "subgraph",
                        "data": {
                            "id": ORPHAN_SUBGRAPH_ID,
                            "name": "stale_subgraph_name",
                            "description": "stale_subgraph_description",
                        },
                    }
                ],
                "edges": [],
            },
            org=default_org,
        )
        StartNode.objects.create(graph=graph, variables={})

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])

        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        assert not id_mapper.has_mapping(EntityType.GRAPH, ORPHAN_SUBGRAPH_ID)

        new_graph_id = id_mapper.get_new_ids(EntityType.GRAPH)[0]
        new_graph = Graph.objects.get(id=new_graph_id)

        subgraph_metadata_nodes = [
            node for node in new_graph.metadata["nodes"] if node["type"] == "subgraph"
        ]
        assert len(subgraph_metadata_nodes) == 1
        assert subgraph_metadata_nodes[0]["data"]["id"] == ORPHAN_SUBGRAPH_ID

    def test_update_metadata_remaps_resolvable_subgraph_reference(self, default_org):
        new_subgraph = Graph.objects.create(
            name="new_subgraph_name",
            description="new subgraph description",
            metadata={"nodes": [], "edges": []},
            org=default_org,
        )
        StartNode.objects.create(graph=new_subgraph, variables={})

        old_subgraph_id = 12345
        id_mapper = IDMapper()
        id_mapper.map(EntityType.GRAPH, old_subgraph_id, new_subgraph.id)

        metadata = {
            "nodes": [
                {
                    "type": "subgraph",
                    "data": {
                        "id": old_subgraph_id,
                        "name": "stale",
                        "description": "stale",
                    },
                }
            ],
            "edges": [],
        }

        strategy = entity_registry.get_strategy(EntityType.GRAPH)
        updated_metadata = strategy.update_metadata(metadata, id_mapper)

        updated_node = updated_metadata["nodes"][0]
        assert updated_node["data"]["id"] == new_subgraph.id
        assert updated_node["data"]["name"] == new_subgraph.name
        assert updated_node["data"]["description"] == new_subgraph.description

        assert metadata["nodes"][0]["data"]["id"] == old_subgraph_id
        assert metadata["nodes"][0]["data"]["name"] == "stale"
        assert metadata["nodes"][0]["data"]["description"] == "stale"
