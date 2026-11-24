"""Point every config at a model row of its own organization.

Configs saved before configurations were scoped to organizations can use another
organization's custom model row. Since the config → model link is RESTRICT, such a link
would block deleting the organization that owns the row, where it used to silently delete
the other organization's config.

Forward, for every LLM and embedding config on a custom row (one with an organization) of
another organization: the config moves to the row of its own organization with the same name
and provider, created from the foreign row when the organization has none. Configs of one
organization that shared a foreign row share the new one. Tags are not copied. The foreign
row and its own organization's configs are left as they are.
"""

from django.db import migrations
from django.db.models import F
from loguru import logger

# Config model -> (its model row model, the row's provider field, the row fields copied on create).
MODEL_ROWS = {
    "LLMConfig": (
        "LLMModel",
        "llm_provider_id",
        ("predefined", "is_custom", "is_visible", "description"),
    ),
    "EmbeddingConfig": (
        "EmbeddingModel",
        "embedding_provider_id",
        ("predefined", "is_custom", "is_visible"),
    ),
}


def own_org_custom_models(apps, schema_editor):
    for config_name, (model_name, provider_field, copied_fields) in MODEL_ROWS.items():
        model_rows = apps.get_model("ai_models", model_name).objects
        configs = (
            apps.get_model("ai_models", config_name)
            .objects.filter(org__isnull=False, model__org__isnull=False)
            .exclude(model__org_id=F("org_id"))
            .select_related("model")
            .order_by("pk")
        )
        for config in configs:
            foreign_row = config.model
            identity = {
                "org_id": config.org_id,
                "name": foreign_row.name,
                provider_field: getattr(foreign_row, provider_field),
            }
            # Filter, not get: a null provider is outside the unique constraint.
            own_row = model_rows.filter(**identity).order_by("pk").first()
            if own_row is None:
                own_row = model_rows.create(
                    **identity,
                    **{field: getattr(foreign_row, field) for field in copied_fields},
                )
            config.model = own_row
            config.save(update_fields=["model"])
            logger.info(
                "Moved {} id={} of org id={} from {} id={} of org id={} to {} id={}",
                config_name,
                config.pk,
                config.org_id,
                model_name,
                foreign_row.pk,
                foreign_row.org_id,
                model_name,
                own_row.pk,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0005_drop_folded_config_columns"),
    ]

    operations = [
        # Backward keeps the configs on their own organization's rows: the cross-org links
        # this migration removes are not wanted back.
        migrations.RunPython(own_org_custom_models, migrations.RunPython.noop),
    ]
