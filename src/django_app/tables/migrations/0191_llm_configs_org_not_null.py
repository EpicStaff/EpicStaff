from django.db import migrations


def _flip(table):
    return migrations.RunSQL(
        sql=f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL;",
        reverse_sql=f"ALTER TABLE {table} ALTER COLUMN org_id DROP NOT NULL;",
    )


class Migration(migrations.Migration):
    """NOT NULL on the strict config tables only. Hybrid *Model tables stay
    nullable (built-ins have org=NULL). Plain RunSQL, no state_operations:
    model state keeps org null=True (from OrgScopedModel); the DB enforces it.
    """

    dependencies = [
        ("tables", "0190_backfill_llm_configs_org"),
    ]

    operations = [
        _flip("tables_llmconfig"),
        _flip("tables_embeddingconfig"),
        _flip("tables_realtimeconfig"),
        _flip("tables_realtimetranscriptionconfig"),
    ]
