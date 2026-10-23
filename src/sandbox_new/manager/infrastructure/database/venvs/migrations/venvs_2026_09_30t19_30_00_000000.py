from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-09-30T19:30:00:000000"
VERSION = "1.36.0"
DESCRIPTION = "Maintain venv.updated_at via a BEFORE UPDATE trigger (DB-managed)"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="venvs", description=DESCRIPTION
    )

    async def create_updated_at_trigger():
        from manager.infrastructure.database.venvs.tables import VenvTable
        await VenvTable.raw(
            "CREATE OR REPLACE FUNCTION set_venv_updated_at() "
            "RETURNS trigger AS $$ BEGIN NEW.updated_at = current_timestamp; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql;"
        ).run()
        await VenvTable.raw(
            "CREATE TRIGGER venv_set_updated_at BEFORE UPDATE ON venv "
            "FOR EACH ROW EXECUTE FUNCTION set_venv_updated_at();"
        ).run()

    async def drop_updated_at_trigger():
        from manager.infrastructure.database.venvs.tables import VenvTable

        await VenvTable.raw(
            "DROP TRIGGER IF EXISTS venv_set_updated_at ON venv;"
        ).run()
        await VenvTable.raw(
            "DROP FUNCTION IF EXISTS set_venv_updated_at();"
        ).run()

    manager.add_raw(create_updated_at_trigger)
    manager.add_raw_backwards(drop_updated_at_trigger)

    return manager
