from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Boolean
from piccolo.columns.indexes import IndexMethod

ID = "2026-11-20T12:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Add venv.is_default, the flag the shared fallback venv is found by"


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    manager.add_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="is_default",
        db_column_name="is_default",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
