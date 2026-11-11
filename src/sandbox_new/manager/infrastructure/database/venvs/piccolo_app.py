import os

from piccolo.conf.apps import AppConfig

from manager.infrastructure.database.venvs import tables

CURRENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))

APP_CONFIG = AppConfig(
    app_name="venvs",
    migrations_folder_path=os.path.join(CURRENT_DIRECTORY, "migrations"),
    table_classes=[
        tables.VenvTable,
        tables.CustomLibraryTable,
        tables.WheelTable,
    ],
    migration_dependencies=[],
    commands=[],
)
