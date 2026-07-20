from django.db import migrations


class Migration(migrations.Migration):
    """NOT NULL on the SourceCollection org column after backfill. Plain RunSQL,
    no state_operations (model state keeps org null=True from OrgScopedModel).
    """

    dependencies = [
        ("tables", "0196_backfill_collections_org"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE tables_sourcecollection ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_sourcecollection ALTER COLUMN org_id DROP NOT NULL;",
        ),
    ]
