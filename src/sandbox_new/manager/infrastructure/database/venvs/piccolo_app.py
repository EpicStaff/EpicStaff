import os

from piccolo.conf.apps import AppConfig

from manager.infrastructure.database.venvs.tables import VenvTable

CURRENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))

APP_CONFIG = AppConfig(
    app_name="venvs",
    migrations_folder_path=os.path.join(CURRENT_DIRECTORY, "migrations"),
    table_classes=[VenvTable],
    migration_dependencies=[],
    commands=[],
)
