"""tables 0258/0259 and agents 0010/0011 copy is_soft_deleted into active and back."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [
    ("tables", "0257_backfill_openai_realtime_model_names"),
    ("agents", "0009_alter_agentdefinition_organization_and_more"),
]
AFTER = [
    ("tables", "0259_drop_is_soft_deleted"),
    ("agents", "0011_drop_is_soft_deleted"),
]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_flag_survives_the_migration_both_ways():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(name="migration-org")
        old_graph = old_apps.get_model("tables", "Graph")
        live = old_graph.objects.create(org=organization, name="Live", metadata={})
        binned = old_graph.objects.create(
            org=organization,
            name="Binned",
            metadata={},
            is_soft_deleted=True,
            soft_deleted_at=timezone.now(),
        )

        new_graph = _migrate(AFTER).get_model("tables", "Graph")
        assert new_graph.objects.get(pk=live.pk).active is True
        assert new_graph.objects.get(pk=binned.pk).active is False

        reverted_graph = _migrate(BEFORE).get_model("tables", "Graph")
        assert reverted_graph.objects.get(pk=live.pk).is_soft_deleted is False
        assert reverted_graph.objects.get(pk=binned.pk).is_soft_deleted is True
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
