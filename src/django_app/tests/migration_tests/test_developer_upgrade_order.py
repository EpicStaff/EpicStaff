"""A database already at developer's migrations upgrades to this branch's leaves.

This branch's soft-delete migrations (tables 0269/0270, agents 0015/0016) descend from
developer's leaf migrations, so they run after developer's tables 0264 has deleted
ConditionalEdge and dropped its table. None of them may touch ConditionalEdge.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# Developer's leaf migrations when it was last merged into this branch. Migrating back
# to them rolls back every migration this branch adds.
DEVELOPER_LEAVES = [
    ("tables", "0268_merge_20261013_1631"),
    ("agents", "0014_merge_20261009_0941"),
    ("rbac", "0006_merge_20261009_0941"),
]
BRANCH_ROOTS = [
    ("tables", "0269_soft_delete_active_flag"),
    ("agents", "0015_soft_delete_active_flag"),
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
