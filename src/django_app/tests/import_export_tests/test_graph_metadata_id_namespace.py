"""Regression tests for the metadata id-namespace collision bug.

``GraphStrategy._update_metadata_node_ids`` unconditionally remaps every
metadata node's ``data["id"]`` through the ``NODE_MAPPING_KEY`` namespace,
even for metadata node types (``subgraph``, ``llm``, ...) whose
``data["id"]`` is a different entity's PK, not a node PK. When a node's old
exported id happens to collide numerically with that other entity's id, a
correct reference gets silently overwritten with an unrelated node id.

These tests fail on unpatched code and must pass once
``_update_metadata_node_ids`` is taught to skip metadata node types that
don't carry a node-id reference.
"""

import pytest
from django.db import connection

from tables.models import Graph, GraphNote, StartNode, SubGraphNode
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.constants import NODE_MAPPING_KEY


def _graph_strategy():
    return entity_registry.get_strategy(EntityType.GRAPH)


def _peek_next_id(model) -> int:
    """Return the id the next row inserted into ``model``'s table will get,
    without shifting the sequence's overall trajectory."""
    table = model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(pg_get_serial_sequence(%s, 'id'))", [table])
        next_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, false)",
            [table, next_id],
        )
    return next_id


@pytest.mark.django_db
class TestUpdateMetadataNodeIdsUnit:
    """Unit-level: force the id-namespace collision directly on a node_mapper
    and assert _update_metadata_node_ids leaves the non-node reference alone.
    """

    def test_subgraph_reference_untouched_when_it_collides_with_a_node_mapping(
        self, default_org
    ):
        subgraph = Graph.objects.create(
            name="subgraph_for_collision_test",
            metadata={"nodes": [], "edges": []},
            org=default_org,
        )

        graph = Graph.objects.create(
            name="parent_for_collision_test",
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
        StartNode.objects.create(graph=graph, variables={})

        # Force the collision: the subgraph's Graph PK is registered as if it
        # were an *old node* export id, mapping to some unrelated new node PK.
        node_mapper = IDMapper()
        unrelated_new_node_id = subgraph.id + 999_999
        node_mapper.map(NODE_MAPPING_KEY, subgraph.id, unrelated_new_node_id)

        _graph_strategy()._update_metadata_node_ids(graph, node_mapper)

        graph.refresh_from_db()
        subgraph_metadata_node = graph.metadata["nodes"][0]
        assert subgraph_metadata_node["data"]["id"] == subgraph.id

    def test_llm_reference_untouched_when_it_collides_with_a_node_mapping(
        self, default_org, llm_config
    ):
        graph = Graph.objects.create(
            name="parent_for_llm_collision_test",
            metadata={
                "nodes": [
                    {
                        "type": "llm",
                        "data": {"id": llm_config.id},
                    }
                ],
                "edges": [],
            },
            org=default_org,
        )
        StartNode.objects.create(graph=graph, variables={})

        node_mapper = IDMapper()
        unrelated_new_node_id = llm_config.id + 999_999
        node_mapper.map(NODE_MAPPING_KEY, llm_config.id, unrelated_new_node_id)

        _graph_strategy()._update_metadata_node_ids(graph, node_mapper)

        graph.refresh_from_db()
        llm_metadata_node = graph.metadata["nodes"][0]
        assert llm_metadata_node["data"]["id"] == llm_config.id


@pytest.mark.django_db
class TestGraphImportMetadataIdNamespaceCollision:
    """Integration-level: a genuine export/import round trip where a node's
    old exported id is made to collide with the freshly-created subgraph's
    real Graph PK (or with an existing LLMConfig id), reproducing the bug
    end-to-end through ExportService/ImportService.
    """

    def test_import_preserves_subgraph_metadata_reference_on_node_id_collision(
        self, export_service, import_service, default_org
    ):
        subgraph = Graph.objects.create(
            name="subgraph_source",
            metadata={"nodes": [], "edges": []},
            org=default_org,
        )
        StartNode.objects.create(graph=subgraph, variables={})

        parent = Graph.objects.create(
            name="parent_source",
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
        GraphNote.objects.create(graph=parent, content="unrelated note")

        export_data = export_service.export_entities(EntityType.GRAPH, [parent.id])

        # GraphStrategy.create_entity always creates a brand-new Graph row
        # for every exported graph (dependencies included), so the subgraph
        # gets a fresh PK on import regardless of the source rows above.
        #
        # The subgraph dependency is imported before the parent graph (see
        # ImportService._resolve_graph_order), and nothing else in this
        # export inserts into the Graph table before it. So the next Graph
        # PK is exactly the id the recreated subgraph will get.
        predicted_new_subgraph_id = _peek_next_id(Graph)

        graph_entities = export_data[EntityType.GRAPH]
        parent_entity = next(g for g in graph_entities if g["id"] == parent.id)
        note_node_data = next(
            n for n in parent_entity["nodes"] if n["node_type"] == "GraphNote"
        )
        # Force the namespace collision: this node's old exported id is set
        # to the id the subgraph graph is about to receive.
        note_node_data["id"] = predicted_new_subgraph_id

        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_subgraph_id = id_mapper.get(EntityType.GRAPH, subgraph.id)
        assert new_subgraph_id == predicted_new_subgraph_id

        new_parent_id = id_mapper.get(EntityType.GRAPH, parent.id)
        new_parent = Graph.objects.get(id=new_parent_id)

        subgraph_metadata_node = next(
            n for n in new_parent.metadata["nodes"] if n["type"] == "subgraph"
        )
        assert subgraph_metadata_node["data"]["id"] == new_subgraph_id

    def test_import_preserves_llm_metadata_reference_on_node_id_collision(
        self, export_service, import_service, default_org, llm_config
    ):
        parent = Graph.objects.create(
            name="parent_llm_source",
            metadata={
                "nodes": [
                    {
                        "type": "llm",
                        "data": {"id": llm_config.id},
                    }
                ],
                "edges": [],
            },
            org=default_org,
        )
        StartNode.objects.create(graph=parent, variables={})
        GraphNote.objects.create(graph=parent, content="unrelated note")

        export_data = export_service.export_entities(EntityType.GRAPH, [parent.id])

        parent_entity = next(
            g for g in export_data[EntityType.GRAPH] if g["id"] == parent.id
        )
        note_node_data = next(
            n for n in parent_entity["nodes"] if n["node_type"] == "GraphNote"
        )
        # Force the namespace collision: this node's old exported id is set
        # to the existing LLMConfig's id referenced by the "llm" metadata node.
        note_node_data["id"] = llm_config.id

        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

        new_parent_id = id_mapper.get(EntityType.GRAPH, parent.id)
        new_parent = Graph.objects.get(id=new_parent_id)

        llm_metadata_node = next(
            n for n in new_parent.metadata["nodes"] if n["type"] == "llm"
        )
        assert llm_metadata_node["data"]["id"] == llm_config.id
