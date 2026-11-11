from collections import defaultdict

from django.db import migrations

from tables.migrations._helpers import plan_duplicate_renames

CUSTOM_NAME_MAX_LENGTH = 250

PROVIDER_REALTIME_CONFIG_MODELS = (
    "OpenAIRealtimeConfig",
    "ElevenLabsRealtimeConfig",
    "GeminiRealtimeConfig",
)


def dedupe_realtime_config_names(apps, schema_editor):
    """Rename same-named configs of one org so the per-org unique constraint can be added.

    The oldest row (lowest pk) keeps its name; later duplicates get a " (N)" suffix.
    """
    for model_name in PROVIDER_REALTIME_CONFIG_MODELS:
        config_model = apps.get_model("tables", model_name)
        rows_by_org = defaultdict(list)
        for pk, org_id, custom_name in config_model.objects.filter(
            org_id__isnull=False
        ).values_list("pk", "org_id", "custom_name"):
            rows_by_org[org_id].append((pk, custom_name))

        for rows in rows_by_org.values():
            renames = plan_duplicate_renames(rows, max_length=CUSTOM_NAME_MAX_LENGTH)
            for pk, new_name in renames.items():
                config_model.objects.filter(pk=pk).update(custom_name=new_name)


class Migration(migrations.Migration):
    # The constraint is added in the next migration: Postgres refuses ALTER TABLE
    # on a table with pending row updates in the same transaction.

    dependencies = [
        ("tables", "0290_systemoneconfig_openai_provider"),
    ]

    operations = [
        migrations.RunPython(dedupe_realtime_config_names, migrations.RunPython.noop),
    ]
