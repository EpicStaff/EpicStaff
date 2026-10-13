"""Migration 0262 on a database that already holds nodes: every row, soft-deleted ones
included, gets its own uuid, and no content hash changes."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tables.models import Graph
from tests.graph_node_builders import MULTIPLE_PER_GRAPH_NODE_MODELS, NODE_MODELS, create_node

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("mock_telegram_service")]

MIGRATION_BEFORE_NODE_UUID = ("tables", "0261_merge_20261007_1300")


def _migrate(targets: list[tuple[str, str]]) -> None:
    # Rows the test just created leave deferred foreign-key checks pending, and
    # Postgres refuses ALTER TABLE on a table with pending trigger events.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    MigrationExecutor(connection).migrate(targets)


def _migrate_to_leaves() -> None:
    _migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


def _uuid_column(model):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(
            cursor, model._meta.db_table
        )
    return next((column for column in description if column.name == "uuid"), None)


@pytest.fixture
def existing_nodes(graph, default_org):
    """One active and one soft-deleted row of every node model, plus a second
    active row where the model allows several per graph."""
    soft_deleted_graph = Graph.objects.create(name="soft-deleted nodes", org=default_org)
    nodes = [create_node(model, graph) for model in NODE_MODELS]
    nodes += [create_node(model, graph) for model in MULTIPLE_PER_GRAPH_NODE_MODELS]
    for model in NODE_MODELS:
        soft_deleted = create_node(model, soft_deleted_graph)
        model._base_manager.filter(pk=soft_deleted.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )
        nodes.append(soft_deleted)
    return nodes


def test_migration_gives_existing_rows_distinct_uuids_and_keeps_content_hashes(existing_nodes):
    before = {
        (type(node), node.pk): (node.uuid, type(node)._base_manager.get(pk=node.pk).generate_hash())
        for node in existing_nodes
    }

    _migrate([MIGRATION_BEFORE_NODE_UUID])
    assert all(_uuid_column(model) is None for model in NODE_MODELS)
    _migrate_to_leaves()

    assert all(_uuid_column(model).null_ok is False for model in NODE_MODELS)
    after = {(model, pk): model._base_manager.get(pk=pk) for (model, pk) in before}
    migrated_uuids = [node.uuid for node in after.values()]
    assert all(migrated_uuids)
    assert len(set(migrated_uuids)) == len(existing_nodes)
    for key, node in after.items():
        uuid_before, hash_before = before[key]
        assert node.uuid != uuid_before
        assert node.generate_hash() == hash_before
    assert any(node.is_soft_deleted for node in after.values())
