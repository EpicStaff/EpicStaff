import csv

import pytest

from tables.import_export.export_tabular_projections.export_classification_decision_table_csv import (
    export_condition_groups_csv,
)


@pytest.mark.django_db
def test_formula_cells_are_neutralized(default_org, cdt_condition_group_factory):
    _, cdt_node, _, _ = cdt_condition_group_factory(default_org, expression="@SUM(A1)", route_code="-1+2")

    rows = list(csv.reader(export_condition_groups_csv(cdt_node).getvalue().splitlines()))

    [rule] = [row for row in rows if row and row[0] == "1"]
    assert rule[3:5] == ["'-1+2", "'@SUM(A1)"]
