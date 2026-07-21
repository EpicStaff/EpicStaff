from django.db import migrations


def _flip(table):
    return migrations.RunSQL(
        sql=f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL;",
        reverse_sql=f"ALTER TABLE {table} ALTER COLUMN org_id DROP NOT NULL;",
    )


class Migration(migrations.Migration):
    """NOT NULL on the strict tool tables only. PythonCodeTool (hybrid) stays
    nullable (built-ins have org=NULL). Plain RunSQL, no state_operations.

    NOTE(dev): confirm db_table names via Model._meta.db_table before running.
    """

    dependencies = [
        ("tables", "0193_backfill_tools_org"),
    ]

    operations = [
        _flip("tables_pythoncodetoolconfig"),
        _flip("tables_mcptool"),
    ]
