import pytest

from tables.models import Graph, GraphNote, StartNode
from tables.import_export.enums import EntityType


@pytest.mark.django_db
class TestGraphImportMetadataIdNamespaceCollision:
    """Integration-level: a genuine export/import round trip where a node's
    old exported id is made to collide with an existing LLMConfig id,
    reproducing the id-namespace collision bug end-to-end through
    ExportService/ImportService.
    """

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
