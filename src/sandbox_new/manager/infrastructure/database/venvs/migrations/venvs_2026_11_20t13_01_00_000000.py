from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-11-20T13:01:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Keep a custom library name unique per scope instead of across the sandbox"

# Separate from the migration that adds the column: Piccolo runs raw steps before
# column changes, so a raw step cannot see a column added in the same migration.


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    async def key_name_by_scope():
        # NULLS NOT DISTINCT: rows not yet given a scope share one namespace, which is
        # the sandbox-wide uniqueness they were stored under.
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        await CustomLibraryTable.raw("DROP INDEX IF EXISTS custom_library_name_key;").run()
        await CustomLibraryTable.raw(
            "CREATE UNIQUE INDEX custom_library_name_key "
            "ON custom_library (scope, name) NULLS NOT DISTINCT "
            "WHERE is_deleted = false AND name IS NOT NULL;"
        ).run()

    async def key_name_across_the_sandbox():
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        await CustomLibraryTable.raw("DROP INDEX IF EXISTS custom_library_name_key;").run()
        await CustomLibraryTable.raw(
            "CREATE UNIQUE INDEX custom_library_name_key "
            "ON custom_library (name) WHERE is_deleted = false;"
        ).run()

    manager.add_raw(key_name_by_scope)
    manager.add_raw_backwards(key_name_across_the_sandbox)

    return manager
