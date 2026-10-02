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


def _create_live_and_binned(model, **fields):
    live = model.objects.create(**fields)
    binned = model.objects.create(**fields, is_soft_deleted=True, soft_deleted_at=timezone.now())
    return live.pk, binned.pk


@pytest.mark.django_db(transaction=True)
def test_flag_survives_the_migration_both_ways():
    """Covers a root (tables.Graph), a node row (tables.TaskNode) and an agents
    row (agents.InlineSurface), so both apps' copy steps run in both directions."""
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(name="migration-org")
        graph_model = old_apps.get_model("tables", "Graph")
        graph = graph_model.objects.create(org=organization, name="Host", metadata={})
        task_node_model = old_apps.get_model("tables", "TaskNode")
        rows = {
            ("tables", "Graph"): _create_live_and_binned(graph_model, org=organization, metadata={}, name="Flow"),
            ("tables", "TaskNode"): _create_live_and_binned(task_node_model, graph=graph, node_name="task", instructions=""),
        }
        live_task_node = task_node_model.objects.get(pk=rows[("tables", "TaskNode")][0])
        binned_task_node = task_node_model.objects.get(pk=rows[("tables", "TaskNode")][1])
        inline_surface_model = old_apps.get_model("agents", "InlineSurface")
        rows[("agents", "InlineSurface")] = (
            inline_surface_model.objects.create(task_node=live_task_node, instructions="").pk,
            inline_surface_model.objects.create(
                task_node=binned_task_node, instructions="", is_soft_deleted=True, soft_deleted_at=timezone.now()
            ).pk,
        )

        new_apps = _migrate(AFTER)
        for (app_label, model_name), (live_pk, binned_pk) in rows.items():
            model = new_apps.get_model(app_label, model_name)
            assert model.objects.get(pk=live_pk).active is True, model_name
            assert model.objects.get(pk=binned_pk).active is False, model_name

        reverted_apps = _migrate(BEFORE)
        for (app_label, model_name), (live_pk, binned_pk) in rows.items():
            model = reverted_apps.get_model(app_label, model_name)
            assert model.objects.get(pk=live_pk).is_soft_deleted is False, model_name
            assert model.objects.get(pk=binned_pk).is_soft_deleted is True, model_name
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
