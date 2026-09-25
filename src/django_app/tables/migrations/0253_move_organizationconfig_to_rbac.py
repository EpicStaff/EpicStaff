# EST-3341/EST-3322: counterpart of rbac/migrations/0003_organizationconfig.py.
# Removes OrganizationConfig from the `tables` app's *state* now that it is
# tracked under `rbac` (mirrors tables/0250's DeleteModel handling for
# Organization/Role/ApiKey/etc.). database_operations stays empty - the
# physical `rbac_organization_config` table is untouched.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0252_merge_20260925_1153"),
        ("rbac", "0003_organizationconfig"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="OrganizationConfig",
                ),
            ],
            database_operations=[],
        ),
    ]
