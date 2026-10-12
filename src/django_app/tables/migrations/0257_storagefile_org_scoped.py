import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Move StorageFile onto OrgScopedModel.

    The model state takes OrgScopedModel's nullable `org`; the DB keeps org_id NOT NULL.
    """

    dependencies = [
        ("rbac", "0003_key_value_tables_resource_type"),
        ("tables", "0256_node_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="storagefile",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="storagefile",
            name="org",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s_set",
                to="rbac.organization",
            ),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE tables_storagefile ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_storagefile ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.AddIndex(
            model_name="storagefile",
            index=models.Index(fields=["org"], name="tables_stor_org_id_df7533_idx"),
        ),
    ]
