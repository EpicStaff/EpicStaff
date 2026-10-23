"""The database server plugin databases live on, registered from what compose runs."""

from plugins.models import PluginDatabaseServer

# The plugins_db service in compose, on the network only it and the plugin node join.
DATABASE_SERVER_NAME = "plugins_db"
DATABASE_SERVER_HOST = "plugins_db"
DATABASE_SERVER_PORT = 5432


def register_database_server() -> PluginDatabaseServer:
    """Create or update the deployment's plugin database server; called only while plugins
    are on (`seed_plugin_node`).

    Independent of the node key: the server row must exist before a package with a database
    is approved, whether or not the node is configured yet.
    """
    server, _ = PluginDatabaseServer.objects.update_or_create(
        name=DATABASE_SERVER_NAME,
        defaults={"host": DATABASE_SERVER_HOST, "port": DATABASE_SERVER_PORT},
    )
    return server


def registered_database_server() -> PluginDatabaseServer | None:
    """The server a new plugin database goes on, or None when none is registered."""
    return PluginDatabaseServer.objects.filter(name=DATABASE_SERVER_NAME).first()
