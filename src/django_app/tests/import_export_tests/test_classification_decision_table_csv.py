import csv

import pytest

from tables.import_export.export_tabular_projections.export_classification_decision_table_csv import (
    export_condition_groups_csv,
)
from tables.models.graph_models import Graph, PythonNode
from tables.models.python_models import PythonCode
from tests.rbac_cross_org_fixtures import beta  # noqa: F401


@pytest.mark.django_db
def test_formula_cells_are_neutralized(default_org, cdt_condition_group_factory):
    _, cdt_node, _, _ = cdt_condition_group_factory(default_org, expression="@SUM(A1)", route_code="-1+2")

    rows = list(csv.reader(export_condition_groups_csv(cdt_node).getvalue().splitlines()))

    [rule] = [row for row in rows if row and row[0] == "1"]
    assert rule[3:5] == ["'-1+2", "'@SUM(A1)"]


@pytest.mark.django_db
def test_routing_to_a_foreign_node_does_not_export_its_name(
    default_org, beta, cdt_condition_group_factory  # noqa: F811
):
    """A reference stored before same-graph validation can point at another
    organization's node; the export must label it by id, never by that node's name."""
    foreign_graph = Graph.objects.create(name="beta graph", org=beta)
    foreign = PythonNode.objects.create(
        graph=foreign_graph,
        node_name="foreign-org-private-name",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )
    graph, cdt_node, _, _ = cdt_condition_group_factory(default_org, next_node_id=foreign.id)
    local = PythonNode.objects.create(
        graph=graph,
        node_name="local-step",
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )
    cdt_node.default_next_node_id = local.id
    cdt_node.next_error_node_id = foreign.id
    cdt_node.save()

    output = export_condition_groups_csv(cdt_node).getvalue()
    rows = list(csv.reader(output.splitlines()))

    assert "foreign-org-private-name" not in output
    assert ["Default Next Step", "local-step"] in rows
    assert ["On Error Go To", f"node #{foreign.id}"] in rows
    [rule] = [row for row in rows if row and row[0] == "1"]
    assert rule[-1] == f"node #{foreign.id}"
