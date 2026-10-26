from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Timestamp
from piccolo.columns.column_types import Timestamptz
from piccolo.columns.defaults.timestamp import TimestampNow
from piccolo.columns.defaults.timestamptz import TimestamptzNow
from piccolo.engine import engine_finder

ID = "2026-10-22T09:48:32:474525"
VERSION = "1.36.0"
DESCRIPTION = "Store venv.created_at and venv.updated_at as timestamptz"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="venvs", description=DESCRIPTION
    )

    # The type change below casts without USING, so Postgres reads the stored values in the session TimeZone; they are UTC.
    async def pin_session_time_zone_to_utc():
        await engine_finder().run_ddl("SET LOCAL TIME ZONE 'UTC'")

    manager.add_raw(pin_session_time_zone_to_utc)
    manager.add_raw_backwards(pin_session_time_zone_to_utc)

    manager.alter_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="created_at",
        db_column_name="created_at",
        params={"default": TimestamptzNow()},
        old_params={"default": TimestampNow()},
        column_class=Timestamptz,
        old_column_class=Timestamp,
        schema=None,
    )

    manager.alter_column(
        table_class_name="VenvTable",
        tablename="venv",
        column_name="updated_at",
        db_column_name="updated_at",
        params={"default": TimestamptzNow()},
        old_params={"default": TimestampNow()},
        column_class=Timestamptz,
        old_column_class=Timestamp,
        schema=None,
    )

    return manager
