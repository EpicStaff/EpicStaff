import pytest

from tables.models.graph_models import Graph, GraphOrganization, StartNode
from tables.models.label_models import Label
from tables.services.copy_services.graph_copy_service import GraphCopyService


@pytest.mark.django_db
def test_copy_seeds_org_values_from_domain_defaults(default_org):
    src = Graph.objects.create(
        name="src", org=default_org, enable_persistent_variables=True
    )
    StartNode.objects.create(
        graph=src,
        variables={
            "variables": {"counter": 7},
            "persistent_variables": {"organization": ["counter"], "user": []},
        },
    )
    # source remembered value differs from the Domain default on purpose:
    # a copy seeds from the copied Domain default (7), not the source store (99).
    GraphOrganization.objects.create(graph=src, persistent_variables={"counter": 99})

    new_graph = GraphCopyService().copy(src, org_id=default_org.id)

    go = GraphOrganization.objects.get(graph=new_graph)
    assert go.persistent_variables == {"counter": 7}
    new_graph.refresh_from_db()
    assert new_graph.enable_persistent_variables is True


@pytest.mark.django_db
def test_copy_does_not_carry_over_tool_scope_labels(default_org):
    src = Graph.objects.create(name="src-with-labels", org=default_org)
    flow_label = Label.objects.create(
        name="flow-label", org=default_org, scope=Label.Scope.FLOW
    )
    tool_label = Label.objects.create(
        name="tool-label", org=default_org, scope=Label.Scope.TOOL
    )
    src.labels.add(flow_label, tool_label)

    new_graph = GraphCopyService().copy(src, org_id=default_org.id)

    new_graph_label_ids = set(new_graph.labels.values_list("id", flat=True))
    assert flow_label.id in new_graph_label_ids
    assert tool_label.id not in new_graph_label_ids
