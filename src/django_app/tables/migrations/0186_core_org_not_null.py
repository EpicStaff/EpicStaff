from django.db import migrations


class Migration(migrations.Migration):
    """Enforce NOT NULL on the core resource org columns after the backfill.

    Plain RunSQL with no state_operations: Django's model state keeps `org`
    as null=True (it comes from the OrgScopedModel mixin), so makemigrations
    detects no drift and the mixin stays nullable for later phases. The DB
    enforces non-null; the viewset mixin always stamps org on create.
    """

    dependencies = [
        ("tables", "0185_backfill_core_org"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE tables_graph ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_graph ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE tables_agent ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_agent ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE tables_crew ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_crew ALTER COLUMN org_id DROP NOT NULL;",
        ),
    ]
