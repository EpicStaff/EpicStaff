"""Regression coverage for the metadata id-namespace collision bug on the
version-restore path.

``GraphVersioningManager.create_graph_from_snapshot`` runs the exact same
two-pass sequence as the import path (``GraphStrategy.update_metadata`` then
``GraphStrategy.recreate_graph_children``), so it automatically inherits the
fix already verified for import (see
``tests/import_export_tests/test_graph_metadata_id_namespace.py``): a
metadata node of type ``subgraph`` carries another Graph's PK in
``data["id"]``, not a node PK, and must never be remapped through the
node-id namespace.

No change is needed in ``tables/graph_versioning/manager.py`` — these tests
exist to confirm the inheritance holds and to catch any future regression
that decouples the two call sites.
"""

import pytest

from tables.import_export.constants import NODE_MAPPING_KEY
from tables.models import Graph, GraphNote, StartNode, SubGraphNode


def _make_parent_with_subgraph_reference(*, default_org):
    subgraph = Graph.objects.create(
        name="subgraph_for_versioning_restore_test",
        metadata={"nodes": [], "edges": []},
        org=default_org,
    )
    StartNode.objects.create(graph=subgraph, variables={})

    parent = Graph.objects.create(
        name="parent_for_versioning_restore_test",
        metadata={
            "nodes": [
                {
                    "type": "subgraph",
                    "data": {
                        "id": subgraph.id,
                        "name": subgraph.name,
                        "description": subgraph.description,
                    },
                }
            ],
            "edges": [],
        },
        org=default_org,
    )
    StartNode.objects.create(graph=parent, variables={})
    SubGraphNode.objects.create(
        graph=parent, node_name="subgraph_node_1", subgraph=subgraph
    )

    return subgraph, parent


def _restore_new_graph_from_snapshot(manager, parent, *, default_org):
    snapshot = manager.create_snapshot(parent)
    deps = manager.collect_dependencies(parent)
    deps_validation = manager.validate_dependencies(deps)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot,
        deps_validation["available"],
        graph_name=parent.name,
        version_name="v1",
        org_id=default_org.id,
    )
    return new_graph


@pytest.mark.django_db
class TestCreateGraphFromSnapshotMetadataSubgraphReference:
    def test_create_graph_from_snapshot_preserves_subgraph_metadata_reference(
        self, manager, default_org
    ):
        subgraph, parent = _make_parent_with_subgraph_reference(default_org=default_org)

        new_graph = _restore_new_graph_from_snapshot(
            manager, parent, default_org=default_org
        )

        subgraph_metadata_node = next(
            node for node in new_graph.metadata["nodes"] if node["type"] == "subgraph"
        )
        assert subgraph_metadata_node["data"]["id"] == subgraph.id

    def test_create_graph_from_snapshot_preserves_subgraph_metadata_reference_on_node_id_collision(
        self, manager, default_org
    ):
        subgraph, parent = _make_parent_with_subgraph_reference(default_org=default_org)
        GraphNote.objects.create(graph=parent, content="unrelated note")

        snapshot = manager.create_snapshot(parent)

        # Force the collision: an unrelated node's old exported id is set to
        # equal the subgraph Graph's real PK. Node recreation will map this
        # old id to a brand-new, unrelated node PK. If the "subgraph"
        # metadata type were not excluded from node-id remapping, that
        # mapping would incorrectly overwrite the subgraph reference too.
        note_node_data = next(
            node for node in snapshot["nodes"] if node["node_type"] == "GraphNote"
        )
        note_node_data["id"] = subgraph.id

        deps = manager.collect_dependencies(parent)
        deps_validation = manager.validate_dependencies(deps)

        new_graph, node_mapper = manager.create_graph_from_snapshot(
            snapshot,
            deps_validation["available"],
            graph_name=parent.name,
            version_name="v1",
            org_id=default_org.id,
        )

        # The collision is real: the recreated note got a new PK distinct
        # from the subgraph's PK it was forced to collide with.
        recreated_note = new_graph.graph_note_list.first()
        assert recreated_note is not None
        assert recreated_note.id != subgraph.id
        assert node_mapper.get(NODE_MAPPING_KEY, subgraph.id) == recreated_note.id

        subgraph_metadata_node = next(
            node for node in new_graph.metadata["nodes"] if node["type"] == "subgraph"
        )
        assert subgraph_metadata_node["data"]["id"] == subgraph.id
