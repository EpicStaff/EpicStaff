import settings
from piccolo.conf.apps import AppRegistry
from piccolo.engine.postgres import PostgresEngine

DB = PostgresEngine(
    config={
        "database": settings.DB_NAME,
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        # Pin every connection (ORM queries and the Piccolo CLI migrations that
        # import this module via PICCOLO_CONF) to the sandbox schema, so all
        # sandbox tables and Piccolo's own migration table live in that namespace,
        # which the sandbox role owns. The schema is created by the crewdb entrypoint.
        "server_settings": {"search_path": settings.DB_SCHEMA},
    }
)
APP_REGISTRY = AppRegistry(apps=["manager.infrastructure.database.venvs.piccolo_app"])
