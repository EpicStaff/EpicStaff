# EST-3341/EST-3322: OrganizationConfig was created under the `tables` app
# (tables/migrations/0210_create_organization_config.py, already applied -
# the physical `rbac_organization_config` table and its rows already exist).
# This migration only moves Django's *state* bookkeeping for the model over
# to the `rbac` app, mirroring how 0001_initial moved Organization/Role/etc.
# No real DDL runs here (database_operations=[]) - the physical table is
# untouched, so no data is at risk.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0002_alter_apikey_table"),
        ("tables", "0210_create_organization_config"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="OrganizationConfig",
                    fields=[
                        (
                            "org",
                            models.OneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                primary_key=True,
                                related_name="config",
                                serialize=False,
                                to="rbac.organization",
                            ),
                        ),
                        ("audit_retention_days", models.PositiveIntegerField(default=0)),
                    ],
                    options={
                        "db_table": "rbac_organization_config",
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
