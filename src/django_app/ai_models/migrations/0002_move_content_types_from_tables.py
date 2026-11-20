"""Relabel the content types of the models that moved from tables to ai_models, keeping their ids.

Last-edit records, plugin ownership and recycle-bin authorship point at these rows by id, so
the rows are renamed in place rather than recreated.
"""

from django.db import migrations

MOVED_MODEL_NAMES = (
    "provider",
    "llmmodel",
    "llmconfig",
    "embeddingmodel",
    "embeddingconfig",
    "llmmodeltag",
    "embeddingmodeltag",
    "llmconfigtag",
    "embeddingconfigtag",
    "defaultmodels",
)


def _relabel(apps, from_app_label: str, to_app_label: str) -> None:
    content_type_model = apps.get_model("contenttypes", "ContentType")
    for model_name in MOVED_MODEL_NAMES:
        moving = content_type_model.objects.filter(app_label=from_app_label, model=model_name)
        if not moving.exists():
            continue
        # A migrate that stopped before this migration lets post_migrate create an empty row
        # under the new label; the old row wins because existing records point at its id.
        content_type_model.objects.filter(app_label=to_app_label, model=model_name).delete()
        moving.update(app_label=to_app_label)


def move_content_types_to_ai_models(apps, schema_editor):
    _relabel(apps, "tables", "ai_models")


def move_content_types_back_to_tables(apps, schema_editor):
    _relabel(apps, "ai_models", "tables")


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0001_initial"),
        ("tables", "0291_move_model_configs_to_ai_models"),
        ("contenttypes", "0002_remove_content_type_name"),
        # The models whose rows a deleted duplicate content type cascades to.
        ("rbac", "0004_resource_last_edit"),
        ("plugins", "0004_service_accounts_hooks_ownership_activity"),
    ]

    operations = [
        migrations.RunPython(move_content_types_to_ai_models, move_content_types_back_to_tables),
    ]
