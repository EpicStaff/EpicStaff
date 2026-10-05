from dataclasses import dataclass

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddField


@dataclass(frozen=True)
class CreatedAtMigration:
    model_label: str
    name_field: str
    previous: tuple[str, str]
    migration: tuple[str, str]


TABLES_PREVIOUS = ("tables", "0258_sourcecollection_drop_user_id")
TABLES_CREATED_AT = ("tables", "0259_created_at_on_authored_configs")

CASES = [
    CreatedAtMigration("tables.LLMConfig", "custom_name", TABLES_PREVIOUS, TABLES_CREATED_AT),
    CreatedAtMigration("tables.EmbeddingConfig", "custom_name", TABLES_PREVIOUS, TABLES_CREATED_AT),
    CreatedAtMigration("tables.RealtimeChannel", "name", TABLES_PREVIOUS, TABLES_CREATED_AT),
    CreatedAtMigration("tables.WebhookTrigger", "path", TABLES_PREVIOUS, TABLES_CREATED_AT),
    CreatedAtMigration(
        "agents.AgentDefinition",
        "name",
        ("agents", "0010_agentdefinition_surface_org_scoped"),
        ("agents", "0011_agentdefinition_created_at"),
    ),
]


def _drop_columns_added_by(migration) -> None:
    # The migration adds every listed column at once, so all of them must be gone
    # before it can be applied again.
    with connection.schema_editor() as editor:
        for operation in migration.operations:
            if isinstance(operation, AddField):
                model = apps.get_model(migration.app_label, operation.model_name)
                editor.remove_field(model, model._meta.get_field(operation.name))


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.model_label)
def test_existing_rows_keep_an_unknown_creation_time(case, default_org):
    # Run FK checks on insert: an ALTER TABLE fails on a table with deferred checks pending.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    loader = MigrationLoader(connection)
    migration = loader.get_migration(*case.migration)
    state_before = loader.project_state(case.previous)
    _drop_columns_added_by(migration)
    app_label, model_name = case.model_label.split(".")
    HistoricalModel = state_before.apps.get_model(app_label, model_name)
    existing = HistoricalModel.objects.create(
        org_id=default_org.id, **{case.name_field: "pre-existing"}
    )

    with connection.schema_editor() as editor:
        migration.apply(state_before, editor)

    Model = apps.get_model(case.model_label)
    assert Model._base_manager.get(pk=existing.pk).created_at is None
    created = Model.objects.create(org=default_org, **{case.name_field: "created-after"})
    assert created.created_at is not None
