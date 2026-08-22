from django.db import migrations

from tables.migrations._helpers import assign_default_org, resolve_default_org

# Strict configs: every row → default org (NOT NULL is enforced next, in 0191).
_STRICT = (
    "tables.LLMConfig",
    "tables.EmbeddingConfig",
    "tables.RealtimeConfig",
    "tables.RealtimeTranscriptionConfig",
)
# Hybrid models: ONLY the custom subset → default org. Built-ins keep org=NULL
# (they stay globally visible); these tables get no NOT NULL flip.
_HYBRID = (
    "tables.LLMModel",
    "tables.EmbeddingModel",
    "tables.RealtimeModel",
    "tables.RealtimeTranscriptionModel",
)


def forwards(apps, schema_editor):
    org = resolve_default_org(apps)
    for label in _STRICT:
        assign_default_org(apps, label, org)
    for label in _HYBRID:
        assign_default_org(apps, label, org, extra_filter={"is_custom": True})


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0189_embeddingconfig_created_by_embeddingconfig_org_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
