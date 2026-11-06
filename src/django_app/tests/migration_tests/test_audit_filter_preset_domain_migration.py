"""tables 0287 gives every audit filter preset a domain. Every preset saved before it
was a session-audit preset, so existing rows must land in `sessions`."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("tables", "0286_rename_filter_preset_org_indexes")]
AFTER = [("tables", "0287_audit_filter_preset_domain")]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_presets_default_to_sessions():
    try:
        old_apps = _migrate(BEFORE)
        org = old_apps.get_model("rbac", "Organization").objects.create(name="Preset domain org")
        author = old_apps.get_model("tables", "User").objects.create(
            email="preset-domain@migration.test", password="!"
        )
        preset_pk = (
            old_apps.get_model("tables", "AuditFilterPreset")
            .objects.create(org_id=org.pk, created_by_id=author.pk, name="Failed", filter_body={})
            .pk
        )

        new_apps = _migrate(AFTER)

        preset_model = new_apps.get_model("tables", "AuditFilterPreset")
        assert preset_model.objects.get(pk=preset_pk).domain == "sessions"
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
