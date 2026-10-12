"""A database already at developer's migrations upgrades to this branch's leaves.

Developer's tables 0264 deletes ConditionalEdge and drops its table. This branch's
soft-delete migrations (tables 0258 onward, agents 0010 onward) are not its ancestors:
the two lines meet only at the 0269 merge. On a database that is already at developer,
they run after the table is gone, so none of them may touch ConditionalEdge. A fresh
database applies them in the other order, which the other migration tests cover.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# The parents of this branch's first soft-delete migrations. Migrating back to them
# rolls back every migration that descends from them, ours and developer's.
BEFORE_BRANCH = [
    ("tables", "0257_backfill_openai_realtime_model_names"),
    ("agents", "0009_alter_agentdefinition_organization_and_more"),
]
# Developer's leaf migrations when it was last merged into this branch.
DEVELOPER_LEAVES = [
    ("tables", "0264_alter_graphversion_snapshot_delete_conditionaledge"),
    ("agents", "0014_merge_20261009_0941"),
    ("rbac", "0006_merge_20261009_0941"),
]
BRANCH_ROOTS = [
    ("tables", "0258_soft_delete_active_flag"),
    ("agents", "0010_soft_delete_active_flag"),
]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)


def _leaves():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


def _applied():
    return MigrationExecutor(connection).recorder.applied_migrations()


@pytest.mark.django_db(transaction=True)
def test_a_developer_database_upgrades_to_this_branch():
    try:
        _migrate(BEFORE_BRANCH)
        _migrate(DEVELOPER_LEAVES)
        applied = _applied()
        assert all(leaf in applied for leaf in DEVELOPER_LEAVES)
        assert not any(root in applied for root in BRANCH_ROOTS)
        assert "tables_conditionaledge" not in connection.introspection.table_names()

        _migrate(_leaves())

        applied = _applied()
        assert all(leaf in applied for leaf in _leaves())
    finally:
        _migrate(_leaves())
