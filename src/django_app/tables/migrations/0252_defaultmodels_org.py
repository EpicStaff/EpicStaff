import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add the OrgScopedModel columns to DefaultModels. `org` stays nullable here
    so 0253 can split the ownerless install-wide row per organization before
    0254 enforces NOT NULL and uniqueness."""

    dependencies = [
        ("rbac", "0002_alter_apikey_table"),
        ("tables", "0251_backfill_session_finished_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="defaultmodels",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="defaultmodels",
            name="org",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s_set",
                to="rbac.organization",
            ),
        ),
        migrations.AddIndex(
            model_name="defaultmodels",
            index=models.Index(fields=["org"], name="tables_defa_org_id_00fdd0_idx"),
        ),
    ]
