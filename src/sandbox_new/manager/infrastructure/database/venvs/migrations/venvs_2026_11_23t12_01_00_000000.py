from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-11-23T12:01:00:000000"
VERSION = "1.36.0"
DESCRIPTION = (
    "Key the default venv by system_key, allow at most one venv per key, drop is_default"
)

# Frozen copy of the key the default venv is found by when this was written.
_DEFAULT_SYSTEM_KEY = "default"

# Separate from the migration that adds the column: Piccolo runs raw steps before
# column changes, so a raw step cannot see a column added in the same migration. The
# same order lets the backfill below still read is_default before it is dropped.


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    async def key_default_venv():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "UPDATE venv SET system_key = {} WHERE is_default", _DEFAULT_SYSTEM_KEY
        ).run()

    async def create_system_key_index():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "CREATE UNIQUE INDEX venv_system_key ON venv (system_key) "
            "WHERE system_key IS NOT NULL;"
        ).run()

    async def drop_system_key_index():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw("DROP INDEX IF EXISTS venv_system_key;").run()

    manager.add_raw(key_default_venv)
    manager.add_raw(create_system_key_index)
    # Dropping the column drops its venv_single_default index with it. Going backwards
    # restores the column with every row unset; the previous migration's backwards
    # marks the default again and recreates the index.
    manager.drop_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="is_default",
        db_column_name="is_default",
        schema=None,
    )
    manager.add_raw_backwards(drop_system_key_index)

    return manager
