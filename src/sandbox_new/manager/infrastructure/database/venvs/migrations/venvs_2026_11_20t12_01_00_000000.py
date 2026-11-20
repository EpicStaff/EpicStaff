from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-11-20T12:01:00:000000"
VERSION = "1.36.0"
DESCRIPTION = (
    "Mark the existing default venv by its flag, and allow at most one venv to carry it"
)

# Frozen copy of the name the default venv was created under when this was written.
_DEFAULT_VENV_NAME = "default"

# Separate from the migration that adds the column: Piccolo runs raw steps before
# column changes, so a raw step cannot see a column added in the same migration.


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    async def mark_default_venv():
        # The oldest row of that name is the one the sandbox built at its first start,
        # before any tenant could create one; a tenant's later copy stays an ordinary venv.
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "UPDATE venv SET is_default = true "
            "WHERE id = (SELECT min(id) FROM venv WHERE name = {})",
            _DEFAULT_VENV_NAME,
        ).run()

    async def create_single_default_index():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "CREATE UNIQUE INDEX venv_single_default ON venv (is_default) WHERE is_default;"
        ).run()

    async def drop_single_default_index():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw("DROP INDEX IF EXISTS venv_single_default;").run()

    manager.add_raw(mark_default_venv)
    manager.add_raw(create_single_default_index)
    manager.add_raw_backwards(drop_single_default_index)

    return manager
