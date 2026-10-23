"""The record of a plugin's own database: its names, its installation id and its app password."""

import secrets
import uuid
from functools import partial

from django.db import transaction
from src.shared.models.plugin_nodes import database_names_for
from tables.services.secrets import secret_encryption

from plugins.audit import log_database_record_created
from plugins.databases.database_server import registered_database_server
from plugins.exceptions import NoPluginDatabaseServerError
from plugins.models import Plugin, PluginDatabase

# `secrets.token_urlsafe(32)` gives 43 URL-safe characters, the form the node's runtime
# credentials accept (`RuntimeDatabaseCredentials`).
APP_PASSWORD_BYTES = 32


class PluginDatabaseRecords:
    """Creates the record of a plugin's database the first time a package with one is approved."""

    def ensure_for(self, plugin: Plugin) -> PluginDatabase:
        """Return the plugin's database record, creating it on the registered server if missing.

        A new record is `pending`, with the names `database_names_for(plugin.identifier)`, a
        fresh installation id and a fresh app password, stored encrypted. Must run inside the
        approval's transaction, which holds the package's lock, so two approvals cannot both
        create one; the audit line is written once it commits.

        Raises:
            NoPluginDatabaseServerError: No plugin database server is registered.
        """
        existing = PluginDatabase.objects.filter(plugin=plugin).first()
        if existing is not None:
            return existing
        server = registered_database_server()
        if server is None:
            raise NoPluginDatabaseServerError()
        names = database_names_for(plugin.identifier)
        sealed = secret_encryption.encrypt(text=secrets.token_urlsafe(APP_PASSWORD_BYTES))
        record = PluginDatabase.objects.create(
            plugin=plugin,
            server=server,
            installation_id=uuid.uuid4().hex,
            database_name=names.database,
            owner_role=names.owner_role,
            app_role=names.app_role,
            job_role=names.job_role,
            app_password_encrypted=sealed.encryptedtext,
        )
        transaction.on_commit(
            partial(
                log_database_record_created,
                identifier=plugin.identifier,
                database=record.database_name,
                server=server.name,
            )
        )
        return record


def app_password_of(record: PluginDatabase) -> str:
    """The app role's password in clear, for the placement's node and nothing else."""
    return secret_encryption.decrypt(encryptedtext=record.app_password_encrypted)
