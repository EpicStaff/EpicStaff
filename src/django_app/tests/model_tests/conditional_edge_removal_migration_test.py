"""tables 0262 deletes conditional edges, the code only they used, and every
reference to them, then drops the table.

The model no longer exists in the current code, so the rows are created through
the historical models of the state just before 0262.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("tables", "0261_merge_20261007_1300")]
AFTER = [("tables", "0262_delete_conditionaledge")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_conditional_edges_and_their_references_are_removed():
    try:
        old_apps = _migrate(BEFORE)
        graph_model = old_apps.get_model("tables", "Graph")
        python_code_model = old_apps.get_model("tables", "PythonCode")
        python_node_model = old_apps.get_model("tables", "PythonNode")
        conditional_edge_model = old_apps.get_model("tables", "ConditionalEdge")
        edge_model = old_apps.get_model("tables", "Edge")
        decision_table_model = old_apps.get_model("tables", "DecisionTableNode")
        condition_group_model = old_apps.get_model("tables", "ConditionGroup")
        classification_table_model = old_apps.get_model(
            "tables", "ClassificationDecisionTableNode"
        )
        classification_group_model = old_apps.get_model("tables", "ClassificationConditionGroup")

        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="migration-org"
        )
        graph = graph_model.objects.create(org=organization, name="Branching flow", description="")

        first_node = python_node_model.objects.create(
            graph=graph,
            node_name="first",
            python_code=python_code_model.objects.create(code="def main(): return 1"),
        )
        shared_code = python_code_model.objects.create(code="def main(): return 'shared'")
        second_node = python_node_model.objects.create(
            graph=graph, node_name="second", python_code=shared_code
        )

        own_code = python_code_model.objects.create(code="def main(): return 'own'")
        branching_edge = conditional_edge_model.objects.create(
            graph=graph, source_node_id=first_node.id, python_code=own_code
        )
        sharing_edge = conditional_edge_model.objects.create(
            graph=graph, source_node_id=second_node.id, python_code=shared_code
        )
        binned_code = python_code_model.objects.create(code="def main(): return 'binned'")
        binned_edge = conditional_edge_model.objects.create(
            graph=graph,
            source_node_id=None,
            python_code=binned_code,
            is_soft_deleted=True,
            soft_deleted_at=timezone.now(),
        )

        kept_edge = edge_model.objects.create(
            graph=graph, start_node_id=first_node.id, end_node_id=second_node.id
        )
        edge_into_branch = edge_model.objects.create(
            graph=graph, start_node_id=first_node.id, end_node_id=branching_edge.id
        )
        edge_out_of_branch = edge_model.objects.create(
            graph=graph, start_node_id=sharing_edge.id, end_node_id=second_node.id
        )

        decision_table = decision_table_model.objects.create(
            graph=graph,
            node_name="table",
            default_next_node_id=branching_edge.id,
            next_error_node_id=second_node.id,
        )
        condition_group = condition_group_model.objects.create(
            decision_table_node=decision_table,
            group_name="group",
            group_type="simple",
            next_node_id=sharing_edge.id,
        )
        classification_table = classification_table_model.objects.create(
            graph=graph,
            node_name="classifier",
            default_next_node_id=second_node.id,
            next_error_node_id=branching_edge.id,
        )
        classification_group = classification_group_model.objects.create(
            classification_decision_table_node=classification_table,
            group_name="route",
            next_node_id=binned_edge.id,
        )

        new_apps = _migrate(AFTER)

        assert "tables_conditionaledge" not in connection.introspection.table_names()

        python_code_ids = set(
            new_apps.get_model("tables", "PythonCode").objects.values_list("id", flat=True)
        )
        assert own_code.id not in python_code_ids
        assert binned_code.id not in python_code_ids
        assert shared_code.id in python_code_ids, "code still used by a node must survive"
        python_node_model = new_apps.get_model("tables", "PythonNode")
        assert python_node_model.objects.filter(graph_id=graph.id).count() == 2

        edge_ids = set(new_apps.get_model("tables", "Edge").objects.values_list("id", flat=True))
        assert kept_edge.id in edge_ids
        assert edge_into_branch.id not in edge_ids
        assert edge_out_of_branch.id not in edge_ids

        decision_table = new_apps.get_model("tables", "DecisionTableNode").objects.get(
            pk=decision_table.pk
        )
        assert decision_table.default_next_node_id is None
        assert decision_table.next_error_node_id == second_node.id
        condition_group = new_apps.get_model("tables", "ConditionGroup").objects.get(
            pk=condition_group.pk
        )
        assert condition_group.next_node_id is None

        classification_table = new_apps.get_model(
            "tables", "ClassificationDecisionTableNode"
        ).objects.get(pk=classification_table.pk)
        assert classification_table.default_next_node_id == second_node.id
        assert classification_table.next_error_node_id is None
        classification_group = new_apps.get_model(
            "tables", "ClassificationConditionGroup"
        ).objects.get(pk=classification_group.pk)
        assert classification_group.next_node_id is None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
