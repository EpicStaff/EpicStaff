from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Varchar

ID = "2026-11-05T12:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Allow custom_library.name to be unset until a wheel or a build names it"


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    manager.alter_column(
        table_class_name="CustomLibraryTable",
        tablename="custom_library",
        column_name="name",
        db_column_name="name",
        params={"null": True, "default": None},
        old_params={"null": False, "default": ""},
        column_class=Varchar,
        old_column_class=Varchar,
        schema=None,
    )

    return manager
