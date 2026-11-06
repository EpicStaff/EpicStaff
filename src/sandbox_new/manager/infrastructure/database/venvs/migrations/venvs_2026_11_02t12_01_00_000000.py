from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-11-02T12:01:00:000000"
VERSION = "1.36.0"
DESCRIPTION = (
    "Maintain custom_library.updated_at via a trigger, and enforce the uniqueness "
    "rules that only hold for rows not marked deleted"
)


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="venvs", description=DESCRIPTION)

    async def create_updated_at_trigger():
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        await CustomLibraryTable.raw(
            "CREATE OR REPLACE FUNCTION set_custom_library_updated_at() "
            "RETURNS trigger AS $$ BEGIN NEW.updated_at = current_timestamp; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql;"
        ).run()
        await CustomLibraryTable.raw(
            "CREATE TRIGGER custom_library_set_updated_at BEFORE UPDATE ON custom_library "
            "FOR EACH ROW EXECUTE FUNCTION set_custom_library_updated_at();"
        ).run()

    async def drop_updated_at_trigger():
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        await CustomLibraryTable.raw(
            "DROP TRIGGER IF EXISTS custom_library_set_updated_at ON custom_library;"
        ).run()
        await CustomLibraryTable.raw(
            "DROP FUNCTION IF EXISTS set_custom_library_updated_at();"
        ).run()

    async def create_unique_indexes():
        # Partial, because deletion is a mark: a marked row keeps its name, version and
        # hash until the reaper removes it, and must not block the next one meanwhile.
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        await CustomLibraryTable.raw(
            "CREATE UNIQUE INDEX custom_library_name_key "
            "ON custom_library (name) WHERE is_deleted = false;"
        ).run()
        await CustomLibraryTable.raw(
            "CREATE UNIQUE INDEX wheel_library_version_key "
            "ON wheel (library, version) "
            "WHERE version IS NOT NULL AND is_deleted = false;"
        ).run()
        await CustomLibraryTable.raw(
            "CREATE UNIQUE INDEX wheel_library_upload_sha256_key "
            "ON wheel (library, upload_sha256) WHERE is_deleted = false;"
        ).run()

    async def drop_unique_indexes():
        from manager.infrastructure.database.venvs.tables import CustomLibraryTable

        for index in (
            "wheel_library_upload_sha256_key",
            "wheel_library_version_key",
            "custom_library_name_key",
        ):
            await CustomLibraryTable.raw(f"DROP INDEX IF EXISTS {index};").run()

    manager.add_raw(create_updated_at_trigger)
    manager.add_raw(create_unique_indexes)
    manager.add_raw_backwards(drop_unique_indexes)
    manager.add_raw_backwards(drop_updated_at_trigger)

    return manager
