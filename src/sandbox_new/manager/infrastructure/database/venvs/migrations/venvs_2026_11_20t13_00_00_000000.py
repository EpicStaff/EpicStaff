from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Varchar
from piccolo.columns.indexes import IndexMethod

ID = "2026-11-20T13:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Add the scope a venv and a custom library belong to"

SCOPE_PARAMS = {
    "length": 255,
    "default": None,
    "null": True,
    "primary_key": False,
    "unique": False,
    "index": False,
    "index_method": IndexMethod.btree,
    "choices": None,
    "db_column_name": None,
    "secret": False,
}


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    manager.add_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="scope",
        db_column_name="scope",
        column_class_name="Varchar",
        column_class=Varchar,
        params=SCOPE_PARAMS,
        schema=None,
    )
    manager.add_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="scope",
        db_column_name="scope",
        column_class_name="Varchar",
        column_class=Varchar,
        params=SCOPE_PARAMS,
        schema=None,
    )

    return manager
