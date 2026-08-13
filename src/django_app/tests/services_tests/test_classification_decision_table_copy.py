import uuid

import pytest

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
    ClassificationDecisionTableNode,
    Graph,
)
from tables.services.copy_services.graph_copy_service import GraphCopyService


@pytest.mark.django_db
def test_copy_classification_decision_table_node_clones_section_with_new_id(
    default_org,
):
    src = Graph.objects.create(name="src", org=default_org)
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

    new_graph = GraphCopyService().copy(src, org_id=default_org.id)

    new_cdt_node = ClassificationDecisionTableNode.objects.get(graph=new_graph)
    new_group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node=new_cdt_node
    )

    assert new_group.section_id is not None
    assert new_group.section_id != section.id

    new_section = new_group.section
    assert new_section.name == "Section A"
    assert new_section.metadata == {"color": "red"}
    assert new_section.classification_decision_table_node_id == new_cdt_node.id


@pytest.mark.django_db
def test_copy_classification_decision_table_node_copies_use_storage_and_remaps_next_node_id(
    default_org,
):
    src = Graph.objects.create(name="src", org=default_org)
    target_node = ClassificationDecisionTableNode.objects.create(
        graph=src, node_name="target"
    )
    cdt_node = ClassificationDecisionTableNode.objects.create(
        graph=src, node_name="cdt", use_storage=True
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=cdt_node,
        group_name="group1",
        order=0,
        next_node_id=target_node.id,
    )

    new_graph = GraphCopyService().copy(src, org_id=default_org.id)

    new_cdt_node = ClassificationDecisionTableNode.objects.get(
        graph=new_graph, node_name="cdt"
    )
    new_target_node = ClassificationDecisionTableNode.objects.get(
        graph=new_graph, node_name="target"
    )
    new_group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node=new_cdt_node
    )

    assert new_cdt_node.use_storage is True

    assert new_group.next_node_id is not None
    assert new_group.next_node_id != target_node.id
    assert new_group.next_node_id == new_target_node.id
