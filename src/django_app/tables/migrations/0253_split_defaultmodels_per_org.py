from django.db import migrations

# DefaultModels FK field -> the org-scoped config model it references.
CONFIG_MODEL_BY_FIELD = {
    "agent_llm_config": "LLMConfig",
    "agent_fcm_llm_config": "LLMConfig",
    "voice_llm_config": "RealtimeConfig",
    "transcription_llm_config": "RealtimeTranscriptionConfig",
    "project_manager_llm_config": "LLMConfig",
    "memory_embedding_config": "EmbeddingConfig",
    "memory_llm_config": "LLMConfig",
}


def split_defaultmodels_per_org(apps, schema_editor):
    """Replace the ownerless install-wide DefaultModels row with one row per
    organization that owns at least one of the configs it references.

    Each new row carries only the fields whose config belongs to that
    organization; the rest stay null. With several ownerless rows the
    lowest pk wins a field both set for the same organization.
    """
    default_models_model = apps.get_model("tables", "DefaultModels")
    ownerless_rows = list(default_models_model.objects.filter(org__isnull=True).order_by("pk"))
    if not ownerless_rows:
        return

    fields_by_org: dict[int, dict[str, int]] = {}
    for row in ownerless_rows:
        for field_name, config_model_name in CONFIG_MODEL_BY_FIELD.items():
            config_id = getattr(row, f"{field_name}_id")
            if config_id is None:
                continue
            config_model = apps.get_model("tables", config_model_name)
            org_id = config_model.objects.values_list("org_id", flat=True).get(pk=config_id)
            fields_by_org.setdefault(org_id, {}).setdefault(f"{field_name}_id", config_id)

    # Delete before creating: the legacy row was written with an explicit pk=1
    # that never advanced the id sequence, so the first new row takes pk 1.
    default_models_model.objects.filter(pk__in=[row.pk for row in ownerless_rows]).delete()
    for org_id, field_values in fields_by_org.items():
        default_models_model.objects.create(org_id=org_id, **field_values)


class Migration(migrations.Migration):
    """Irreversible: the per-org rows cannot be merged back into one global row
    without choosing between organizations, so reversing raises IrreversibleError."""

    dependencies = [
        ("tables", "0252_defaultmodels_org"),
    ]

    operations = [
        migrations.RunPython(split_defaultmodels_per_org),
    ]
