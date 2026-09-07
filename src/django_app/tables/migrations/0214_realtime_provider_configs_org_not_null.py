from django.db import migrations


class Migration(migrations.Migration):
    """Enforce NOT NULL on org_id for the three realtime provider config
    tables after the backfill.

    Plain RunSQL with no state_operations: Django's model state keeps `org`
    as null=True (it comes from the OrgScopedModel mixin), so makemigrations
    detects no drift and the mixin stays nullable for later phases. The DB
    enforces non-null; the viewset mixin always stamps org on create. Same
    pattern as 0209_realtime_channel_org_not_null.py.
    """

    dependencies = [
        ("tables", "0213_backfill_realtime_provider_configs_org"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE openai_realtime_config ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE openai_realtime_config ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE elevenlabs_realtime_config ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE elevenlabs_realtime_config ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE gemini_realtime_config ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE gemini_realtime_config ALTER COLUMN org_id DROP NOT NULL;",
        ),
    ]
