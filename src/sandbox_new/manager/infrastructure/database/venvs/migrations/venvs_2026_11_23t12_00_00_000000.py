from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Varchar
from piccolo.columns.indexes import IndexMethod

ID = "2026-11-23T12:00:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Add venv.system_key, the key a venv the sandbox owns is found by"

# Frozen copy of the key the default venv is found by when this was written.
_DEFAULT_SYSTEM_KEY = "default"


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    manager.add_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="system_key",
        db_column_name="system_key",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
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
        },
        schema=None,
    )

    async def restore_default_flag():
        # Runs before the column is dropped, while the backwards of the next migration
        # has already brought `is_default` back: both columns exist here. The node
        # venvs go, since the code this rolls back to does not know them.
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "UPDATE venv SET is_default = true WHERE system_key = {}", _DEFAULT_SYSTEM_KEY
        ).run()
        await VenvTable.raw(
            "CREATE UNIQUE INDEX venv_single_default ON venv (is_default) WHERE is_default;"
        ).run()
        await VenvTable.raw(
            "DELETE FROM venv WHERE system_key IS NOT NULL AND system_key <> {}",
            _DEFAULT_SYSTEM_KEY,
        ).run()

    manager.add_raw_backwards(restore_default_flag)

    return manager
