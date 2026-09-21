"""Regression tests for the metadata id-namespace collision bug in the
flow-copy path.

``GraphCopyService._remap_metadata_node_ids`` unconditionally remapped every
metadata node's ``data["id"]`` through ``node_id_map``, even for metadata
node types (``subgraph``, ``llm``, ...) whose ``data["id"]`` is a different
entity's PK, not a node PK. When a copied node's old id happened to collide
numerically with that other entity's id, a correct reference got silently
overwritten with an unrelated node id.

These tests fail on unpatched code and must pass once
``_remap_metadata_node_ids`` is taught to skip metadata node types that
don't carry a node-id reference.
"""

import pytest

from tables.models import Graph, StartNode, SubGraphNode
from tables.services.copy_services.graph_copy_service import GraphCopyService


@pytest.mark.django_db
class TestRemapMetadataNodeIdsUnit:
    def test_subgraph_reference_untouched_when_it_collides_with_a_node_mapping(
        self, default_org
    ):
        child_graph = Graph.objects.create(
            name="child_for_copy_collision_test",
            metadata={"nodes": [], "edges": []},
            org=default_org,
        )

        parent_graph = Graph.objects.create(
            name="parent_for_copy_collision_test",
            metadata={
                "nodes": [
                    {
                        "type": "subgraph",
                        "data": {
                            "id": child_graph.id,
                            "name": child_graph.name,
                            "description": child_graph.description,
                        },
                    }
                ],
                "edges": [],
            },
            org=default_org,
        )
        StartNode.objects.create(graph=parent_graph, variables={})

        # Force the collision: some unrelated old node PK is mapped to the
        # same value as the child graph's PK.
        unrelated_old_node_id = child_graph.id + 999_999
        node_id_map = {unrelated_old_node_id: child_graph.id}

        GraphCopyService()._remap_metadata_node_ids(parent_graph, node_id_map)

        parent_graph.refresh_from_db()
        subgraph_metadata_node = parent_graph.metadata["nodes"][0]
        assert subgraph_metadata_node["data"]["id"] == child_graph.id


@pytest.mark.django_db
class TestGraphCopyMetadataSubgraphReference:
    def test_copy_preserves_subgraph_metadata_reference_on_node_id_collision(
        self, default_org
    ):
        child_graph = Graph.objects.create(
            name="child_graph_source",
            metadata={"nodes": [], "edges": []},
            org=default_org,
        )
        StartNode.objects.create(graph=child_graph, variables={})

        parent_graph = Graph.objects.create(
            name="parent_graph_source",
            metadata={
                "nodes": [
                    {
                        "type": "subgraph",
                        "data": {
                            "id": child_graph.id,
                            "name": child_graph.name,
                            "description": child_graph.description,
                        },
                    }
                ],
                "edges": [],
            },
            org=default_org,
        )
        StartNode.objects.create(graph=parent_graph, variables={})
        SubGraphNode.objects.create(
            graph=parent_graph, node_name="subgraph_node_1", subgraph=child_graph
        )

        copy_service = GraphCopyService()
        new_parent_graph = copy_service.copy(parent_graph, org_id=parent_graph.org_id)

        # Force the collision that could arise from a real copy: some
        # unrelated source node's old PK happens to equal the child graph's
        # PK, and would map to the corresponding copied node's new PK.
        unrelated_old_node_id = child_graph.id + 999_999
        node_id_map = {unrelated_old_node_id: child_graph.id}
        copy_service._remap_metadata_node_ids(new_parent_graph, node_id_map)

        subgraph_metadata_node = next(
            node
            for node in new_parent_graph.metadata["nodes"]
            if node["type"] == "subgraph"
        )
        assert subgraph_metadata_node["data"]["id"] == child_graph.id
