from django.db import migrations, models


class Migration(migrations.Migration):
    """Enforce one DefaultModels row per organization.

    NOT NULL is plain RunSQL with no state_operations, like
    0191_llm_configs_org_not_null.py: model state keeps `org` null=True (it
    comes from OrgScopedModel) and the DB enforces non-null.
    """

    dependencies = [
        ("tables", "0253_split_defaultmodels_per_org"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE tables_defaultmodels ALTER COLUMN org_id SET NOT NULL;",
            reverse_sql="ALTER TABLE tables_defaultmodels ALTER COLUMN org_id DROP NOT NULL;",
        ),
        migrations.AddConstraint(
            model_name="defaultmodels",
            constraint=models.UniqueConstraint(fields=("org",), name="unique_defaultmodels_per_org"),
        ),
    ]
