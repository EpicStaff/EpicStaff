import uuid

import pytest

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
    ClassificationDecisionTableNode,
    Graph,
)
from tables.import_export.enums import EntityType


@pytest.mark.django_db
def test_import_classification_decision_table_node_clones_section_with_new_id(
    default_org, export_service, import_service
):
    src = Graph.objects.create(name="cdt-section-src", org=default_org)
    cdt_node = ClassificationDecisionTableNode.objects.create(
        graph=src, node_name="cdt"
    )
    section = ClassificationConditionGroupSection.objects.create(
        id=uuid.uuid4(),
        classification_decision_table_node=cdt_node,
        name="Section A",
        metadata={"color": "red"},
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=cdt_node,
        group_name="group1",
        order=0,
        section=section,
    )

    export_data = export_service.export_entities(EntityType.GRAPH, [src.id])

    # Import back into the same running system while the source graph (and
    # section row, same UUID PK) still exists.
    id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

    new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    new_cdt_node = ClassificationDecisionTableNode.objects.get(graph_id=new_graph_id)
    new_group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node=new_cdt_node
    )

    assert new_group.section_id is not None
    assert new_group.section_id != section.id

    new_section = new_group.section
    assert new_section.name == "Section A"
    assert new_section.metadata == {"color": "red"}
    assert new_section.classification_decision_table_node_id == new_cdt_node.id
