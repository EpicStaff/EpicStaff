import pytest

from tables.models import Graph, StartNode
from tables.import_export.enums import EntityType

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
