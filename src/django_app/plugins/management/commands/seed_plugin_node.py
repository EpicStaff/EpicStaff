from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from plugins.databases.database_server import register_database_server
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.nodes.node_registration import register_configured_node


class Command(BaseCommand):
    help = (
        "Register the plugin node from PLUGINS_NODE_NAME, PLUGINS_NODE_KEY and "
        "PLUGINS_NODE_UID_RANGE, the plugin database server, and the first plugin signing key. "
        "Does nothing while plugins are off; registers no node while the key is none."
    )

    def handle(self, *args, **options):
        if settings.PLUGINS_ENABLED:
            signing_key = PluginSigningKeyService().ensure_key()
            self.stdout.write(f"Plugin contexts are signed with key {signing_key.kid}.")
            server = register_database_server()
            self.stdout.write(
                f"Plugin database server {server.name!r} registered at {server.host}:{server.port}."
            )
        try:
            node = register_configured_node()
        except ValueError as error:
            raise CommandError(str(error)) from None
        if node is None:
            self.stdout.write(
                "Plugin node not registered: plugins are off or PLUGINS_NODE_KEY is none."
            )
            return
        self.stdout.write(
            f"Plugin node {node.name!r} registered (user ids {node.uid_range_start}-{node.uid_range_end})."
        )
