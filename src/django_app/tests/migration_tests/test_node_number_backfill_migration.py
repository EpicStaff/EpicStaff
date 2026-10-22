"""tables 0272 moves each node's "#N" badge out of node_name / metadata["nodeNumber"]
into node_number, seeds Graph.node_number_seq, and rewrites version snapshots the
same way.

Rows are created through the historical models of the state just before 0272, so
NumberedNode.save() never runs and node_number starts out NULL, as on a real install.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("tables", "0271_node_number")]
AFTER = [("tables", "0272_backfill_node_number")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_latest():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _new_graph(old_apps, organization, name):
    return old_apps.get_model("tables", "Graph").objects.create(
        org=organization, name=name, description="", metadata={}
    )


def _python_node(old_apps, graph, node_name, metadata=None, **extra):
    python_code = old_apps.get_model("tables", "PythonCode").objects.create(
        code="def main(): return 1"
    )
    return old_apps.get_model("tables", "PythonNode").objects.create(
        graph=graph,
        node_name=node_name,
        python_code=python_code,
        metadata=metadata if metadata is not None else {},
        **extra,
    )


def _state(new_apps, model_name, node):
    row = new_apps.get_model("tables", model_name)._base_manager.get(pk=node.pk)
    return row.node_name, row.node_number, row.metadata


def _graph_seq(new_apps, graph):
    return new_apps.get_model("tables", "Graph")._base_manager.get(pk=graph.pk).node_number_seq


@pytest.mark.django_db(transaction=True)
def test_live_nodes_get_their_badge_number_and_lose_the_name_suffix():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="migration-org"
        )

        main_graph = _new_graph(old_apps, organization, "Main")
        matching = _python_node(
            old_apps,
            main_graph,
            "Python-Node #3",
            {"nodeNumber": 3, "position": {"x": 1, "y": 2}},
        )
        disagreeing = _python_node(old_apps, main_graph, "Step #2", {"nodeNumber": 5})
        name_only = old_apps.get_model("tables", "TaskNode").objects.create(
            graph=main_graph, node_name="Agent #4", instructions=""
        )
        bare_badge = _python_node(old_apps, main_graph, "#7", {"nodeNumber": 7})
        boolean_number = _python_node(old_apps, main_graph, "Flag #9", {"nodeNumber": True})
        unnumbered = _python_node(old_apps, main_graph, "Plain")
        oversized_suffix = _python_node(old_apps, main_graph, "Order #20240101123456")
        binned = _python_node(
            old_apps,
            main_graph,
            "Binned #6",
            {"nodeNumber": 6},
            active=False,
            soft_deleted_at=timezone.now(),
        )
        start_node = old_apps.get_model("tables", "StartNode").objects.create(
            graph=main_graph, metadata={"nodeNumber": 1}
        )
        end_node = old_apps.get_model("tables", "EndNode").objects.create(
            graph=main_graph, output_map={}, metadata={"nodeNumber": 2}
        )
        note = old_apps.get_model("tables", "GraphNote").objects.create(
            graph=main_graph, content="Note #9", metadata={"nodeNumber": 9}
        )

        duplicate_graph = _new_graph(old_apps, organization, "Duplicates")
        first_duplicate = _python_node(old_apps, duplicate_graph, "Copy #2", {"nodeNumber": 2})
        second_duplicate = _python_node(old_apps, duplicate_graph, "Copy #2", {"nodeNumber": 2})
        third_node = _python_node(old_apps, duplicate_graph, "Other #4", {"nodeNumber": 4})

        router_graph = _new_graph(old_apps, organization, "Routers")
        classification_model = old_apps.get_model("tables", "ClassificationDecisionTableNode")
        first_router = classification_model.objects.create(
            graph=router_graph, node_name="Router #1", metadata={"nodeNumber": 1}
        )
        second_router = classification_model.objects.create(
            graph=router_graph, node_name="Router #2", metadata={"nodeNumber": 2}
        )

        empty_graph = _new_graph(old_apps, organization, "Empty")

        new_apps = _migrate(AFTER)

        assert _state(new_apps, "PythonNode", matching) == (
            "Python-Node",
            3,
            {"position": {"x": 1, "y": 2}},
        )
        assert _state(new_apps, "PythonNode", disagreeing) == ("Step #2", 5, {})
        assert _state(new_apps, "TaskNode", name_only) == ("Agent", 4, {})
        assert _state(new_apps, "PythonNode", bare_badge) == ("#7", 7, {})
        # A boolean is not a number: the name's suffix decides instead.
        assert _state(new_apps, "PythonNode", boolean_number) == ("Flag", 9, {})
        assert _state(new_apps, "PythonNode", binned) == ("Binned", 6, {})
        # Highest kept number is 9, so the node without any number comes next.
        assert _state(new_apps, "PythonNode", unnumbered) == ("Plain", 10, {})
        # A suffix far beyond any real badge (here a date stamp) is part of the name.
        assert _state(new_apps, "PythonNode", oversized_suffix) == (
            "Order #20240101123456",
            11,
            {},
        )
        assert _graph_seq(new_apps, main_graph) == 11

        start_metadata = (
            new_apps.get_model("tables", "StartNode")._base_manager.get(pk=start_node.pk).metadata
        )
        end_metadata = (
            new_apps.get_model("tables", "EndNode")._base_manager.get(pk=end_node.pk).metadata
        )
        note_row = new_apps.get_model("tables", "GraphNote")._base_manager.get(pk=note.pk)
        assert start_metadata == {"nodeNumber": 1}
        assert end_metadata == {"nodeNumber": 2}
        assert (note_row.content, note_row.metadata) == ("Note #9", {"nodeNumber": 9})

        assert _state(new_apps, "PythonNode", first_duplicate) == ("Copy", 2, {})
        assert _state(new_apps, "PythonNode", second_duplicate) == ("Copy", 5, {})
        assert _state(new_apps, "PythonNode", third_node) == ("Other", 4, {})
        assert _graph_seq(new_apps, duplicate_graph) == 5

        routers = "ClassificationDecisionTableNode"
        assert _state(new_apps, routers, first_router) == ("Router", 1, {})
        assert _state(new_apps, routers, second_router) == ("Router", 2, {})
        assert _graph_seq(new_apps, router_graph) == 2

        assert _graph_seq(new_apps, empty_graph) == 0
    finally:
        _migrate_to_latest()


@pytest.mark.django_db(transaction=True)
def test_version_snapshots_are_rewritten_with_the_same_rule():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="migration-org"
        )
        graph = _new_graph(old_apps, organization, "Versioned")
        snapshot = {
            "name": "Versioned",
            "version": 3,
            "nodes": [
                {
                    "id": 10,
                    "node_type": "PythonNode",
                    "node_name": "Python-Node #3",
                    "metadata": {"nodeNumber": 3, "position": {"x": 0, "y": 0}},
                },
                {
                    "id": 11,
                    "node_type": "PythonNode",
                    "node_name": "Twin #3",
                    "metadata": {"nodeNumber": 3},
                },
                {
                    "id": 12,
                    "node_type": "AgentNode",
                    "node_name": "Step #2",
                    "metadata": {"nodeNumber": 5},
                },
                {"id": 13, "node_type": "SubgraphNode", "node_name": "Inner"},
                {"id": 14, "node_type": "StartNode", "metadata": {"nodeNumber": 1}},
                {
                    "id": 15,
                    "node_type": "GraphNote",
                    "content": "Note",
                    "metadata": {"nodeNumber": 4},
                },
            ],
            "edge_list": [{"start_node_id": 14, "end_node_id": 10}],
        }
        version_model = old_apps.get_model("tables", "GraphVersion")
        live_version = version_model.objects.create(graph=graph, name="v1", snapshot=snapshot)
        binned_version = version_model.objects.create(
            graph=graph,
            name="v0",
            snapshot={
                "nodes": [
                    {"id": 1, "node_type": "TaskNode", "node_name": "Task #1", "metadata": {}}
                ]
            },
            active=False,
            soft_deleted_at=timezone.now(),
        )
        without_nodes = version_model.objects.create(graph=graph, name="v2", snapshot={})

        new_apps = _migrate(AFTER)
        new_version_model = new_apps.get_model("tables", "GraphVersion")

        rewritten = new_version_model._base_manager.get(pk=live_version.pk).snapshot
        assert [
            (node.get("node_name"), node.get("node_number"), node.get("metadata"))
            for node in rewritten["nodes"]
        ] == [
            ("Python-Node", 3, {"position": {"x": 0, "y": 0}}),
            ("Twin", 6, {}),
            ("Step #2", 5, {}),
            ("Inner", 7, None),
            (None, None, {"nodeNumber": 1}),
            (None, None, {"nodeNumber": 4}),
        ]
        # Only node content changes; restore still converts from the recorded version.
        assert rewritten["version"] == 3
        assert rewritten["edge_list"] == [{"start_node_id": 14, "end_node_id": 10}]

        binned_nodes = new_version_model._base_manager.get(pk=binned_version.pk).snapshot["nodes"]
        assert [(node["node_name"], node["node_number"]) for node in binned_nodes] == [
            ("Task", 1)
        ]
        assert new_version_model._base_manager.get(pk=without_nodes.pk).snapshot == {}
    finally:
        _migrate_to_latest()
