"""Migration 0265 stamps the uuid of each node that still exists into the saved graph
versions of its graph, through the historical models Django gives the migration."""

import copy
import uuid
from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tables.models import Graph, GraphVersion
from tables.models.graph_models import GraphNote, PythonNode, StartNode
from tests.graph_node_builders import create_every_node, create_node

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("mock_telegram_service")]

MIGRATION_BEFORE_STAMPING = ("tables", "0264_merge_0262_node_uuid_0263_merge_20261009_0941")
stamping_migration = import_module("tables.migrations.0265_stamp_node_uuids_into_graph_versions")
node_uuid_migration = import_module("tables.migrations.0262_node_uuid")

# The models frozen in the migration, not the current node registry: a node type added
# later must not make this test expect a uuid the migration was never meant to stamp.
STAMPED_NODE_MODELS = tuple(
    apps.get_model("tables", name) for name in stamping_migration.NODE_MODEL_NAMES
)


def _migrate(targets: list[tuple[str, str]]) -> None:
    MigrationExecutor(connection).migrate(targets)


def _run_stamping_migration() -> None:
    """Unapply the stamping migration (its reverse is a no-op) and apply it again."""
    _migrate([MIGRATION_BEFORE_STAMPING])
    _migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


def _snapshot_node(node) -> dict:
    return {"id": node.pk, "node_type": type(node).__name__, "node_name": f"node {node.pk}"}


def _create_version(graph: Graph, nodes: list, *, format_version: int = 3) -> GraphVersion:
    snapshot = {
        "version": format_version,
        "name": graph.name,
        "nodes": [_snapshot_node(node) for node in nodes],
        "edges": [{"start_node_id": nodes[0].pk, "end_node_id": nodes[-1].pk}] if nodes else [],
        "metadata": {"nodes": [{"id": "canvas-1", "position": {"x": 1, "y": 2}}]},
    }
    return GraphVersion.objects.create(graph=graph, name="saved", snapshot=snapshot)


def _soft_delete(model, pk: int) -> None:
    model._base_manager.filter(pk=pk).update(is_soft_deleted=True, soft_deleted_at=timezone.now())


def _stored_snapshot(version: GraphVersion) -> dict:
    return GraphVersion._base_manager.get(pk=version.pk).snapshot


def _without_uuids(snapshot: dict) -> dict:
    result = copy.deepcopy(snapshot)
    for node in result["nodes"]:
        node.pop("uuid", None)
    return result


def _row_uuid(node) -> str:
    return str(type(node)._base_manager.get(pk=node.pk).uuid)


def test_stamps_the_same_models_that_got_the_uuid_column():
    stamped_names = {name.lower() for name in stamping_migration.NODE_MODEL_NAMES}
    assert stamped_names == set(node_uuid_migration.NODE_MODEL_NAMES)


def test_every_node_model_is_stamped_and_other_keys_stay(graph):
    nodes = list(create_every_node(graph, models=STAMPED_NODE_MODELS).values())
    version = _create_version(graph, nodes)
    snapshot_before = copy.deepcopy(version.snapshot)

    _run_stamping_migration()

    snapshot = _stored_snapshot(version)
    assert [node["uuid"] for node in snapshot["nodes"]] == [_row_uuid(node) for node in nodes]
    assert _without_uuids(snapshot) == snapshot_before


def test_nodes_deleted_since_the_version_get_no_uuid(graph):
    kept = create_node(PythonNode, graph)
    deleted = create_node(GraphNote, graph)
    version = _create_version(graph, [kept, deleted])
    GraphNote.objects.filter(pk=deleted.pk).delete()

    _run_stamping_migration()

    kept_entry, deleted_entry = _stored_snapshot(version)["nodes"]
    assert kept_entry["uuid"] == _row_uuid(kept)
    assert "uuid" not in deleted_entry


def test_version_whose_nodes_are_all_gone_is_unchanged(graph):
    nodes = [create_node(GraphNote, graph), create_node(PythonNode, graph)]
    version = _create_version(graph, nodes)
    for node in nodes:
        type(node).objects.filter(pk=node.pk).delete()
    create_node(StartNode, graph)

    _run_stamping_migration()

    assert _stored_snapshot(version) == version.snapshot


@pytest.mark.parametrize("format_version", [1, 2])
def test_old_format_snapshot_is_stamped_and_keeps_its_version(graph, format_version):
    node = create_node(PythonNode, graph)
    version = _create_version(graph, [node], format_version=format_version)

    _run_stamping_migration()

    snapshot = _stored_snapshot(version)
    assert snapshot["version"] == format_version
    assert snapshot["nodes"][0]["uuid"] == _row_uuid(node)


def test_empty_database_is_a_no_op():
    assert not GraphVersion._base_manager.exists()

    _run_stamping_migration()

    assert not GraphVersion._base_manager.exists()


def test_uuid_already_in_the_snapshot_is_kept(graph):
    stamped, unstamped = create_node(PythonNode, graph), create_node(GraphNote, graph)
    version = _create_version(graph, [stamped, unstamped])
    existing_uuid = str(uuid.uuid4())
    version.snapshot["nodes"][0]["uuid"] = existing_uuid
    version.save(update_fields=["snapshot"])

    _run_stamping_migration()

    stamped_entry, unstamped_entry = _stored_snapshot(version)["nodes"]
    assert stamped_entry["uuid"] == existing_uuid
    assert unstamped_entry["uuid"] == _row_uuid(unstamped)


def test_second_run_changes_nothing(graph):
    version = _create_version(graph, [create_node(PythonNode, graph)])
    _run_stamping_migration()
    snapshot_after_first_run = _stored_snapshot(version)

    with CaptureQueriesContext(connection) as queries:
        _run_stamping_migration()

    assert _stored_snapshot(version) == snapshot_after_first_run
    assert not [
        query for query in queries if query["sql"].startswith('UPDATE "tables_graphversion"')
    ]


def test_versions_beyond_one_batch_are_all_stamped(graph, monkeypatch):
    monkeypatch.setattr(stamping_migration, "VERSION_BATCH_SIZE", 2)
    node = create_node(PythonNode, graph)
    versions = [_create_version(graph, [node]) for _ in range(3)]

    with CaptureQueriesContext(connection) as queries:
        _run_stamping_migration()

    assert all(
        _stored_snapshot(version)["nodes"][0]["uuid"] == _row_uuid(node) for version in versions
    )
    version_updates = [
        query for query in queries if query["sql"].startswith('UPDATE "tables_graphversion"')
    ]
    assert len(version_updates) == 2


def test_soft_deleted_graph_version_and_node_rows_are_stamped(default_org):
    graph = Graph.objects.create(name="deleted flow", org=default_org)
    node = create_node(PythonNode, graph)
    version = _create_version(graph, [node])
    _soft_delete(PythonNode, node.pk)
    _soft_delete(GraphVersion, version.pk)
    _soft_delete(Graph, graph.pk)

    _run_stamping_migration()

    assert _stored_snapshot(version)["nodes"][0]["uuid"] == _row_uuid(node)


def test_node_ids_are_matched_only_inside_their_own_graph(graph, default_org):
    other_graph = Graph.objects.create(name="other", org=default_org)
    own_node = create_node(PythonNode, graph)
    other_node = create_node(PythonNode, other_graph)
    # Not a real snapshot: it names a node of another graph, which must not match.
    version = _create_version(graph, [own_node, other_node])
    other_version = _create_version(other_graph, [other_node])

    _run_stamping_migration()

    own_entry, foreign_entry = _stored_snapshot(version)["nodes"]
    assert own_entry["uuid"] == _row_uuid(own_node)
    assert "uuid" not in foreign_entry
    assert _stored_snapshot(other_version)["nodes"][0]["uuid"] == _row_uuid(other_node)


def test_malformed_snapshots_and_nodes_are_skipped(graph):
    node = create_node(PythonNode, graph)
    malformed_snapshots = [[], {}, {"nodes": "not a list"}, {"nodes": None}]
    malformed_versions = [
        GraphVersion.objects.create(graph=graph, name="bad", snapshot=snapshot)
        for snapshot in malformed_snapshots
    ]
    malformed_nodes = ["text", {"node_type": "PythonNode"}, {"id": str(node.pk)}, {"id": True}]
    version = GraphVersion.objects.create(
        graph=graph,
        name="mixed",
        snapshot={"version": 3, "nodes": [*malformed_nodes, _snapshot_node(node)]},
    )

    _run_stamping_migration()

    assert [_stored_snapshot(bad) for bad in malformed_versions] == malformed_snapshots
    nodes = _stored_snapshot(version)["nodes"]
    assert nodes[:-1] == malformed_nodes
    assert nodes[-1]["uuid"] == _row_uuid(node)


def test_reverse_keeps_the_stamped_uuids(graph):
    node = create_node(PythonNode, graph)
    version = _create_version(graph, [node])
    _run_stamping_migration()

    _migrate([MIGRATION_BEFORE_STAMPING])

    assert _stored_snapshot(version)["nodes"][0]["uuid"] == _row_uuid(node)
