from django.db import migrations


class Migration(migrations.Migration):
    """NOT NULL on the Label org column after backfill. Plain RunSQL, no
    state_operations (model state keeps org null=True from OrgScopedModel).
    """

    dependencies = [
        ("tables", "0199_backfill_labels_org"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE tables_label ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_label ALTER COLUMN org_id DROP NOT NULL;",
        ),
    ]
