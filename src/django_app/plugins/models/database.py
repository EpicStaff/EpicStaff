from django.db import models
from src.shared.models.plugin_nodes import MAX_LAST_ERROR_LENGTH

from plugins.models.enums import PluginDatabaseState
from plugins.models.plugin import Plugin

# Postgres keeps at most 63 characters of an identifier.
DATABASE_OBJECT_NAME_LENGTH = 63


class PluginDatabaseServer(models.Model):
    """A Postgres server that plugin databases live on, as the plugin node reaches it.

    Deployment-wide. `seed_plugin_node` seeds the one server this version has while plugins
    are on; django_app never connects to it.
    """

    name = models.CharField(max_length=64, unique=True)
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class PluginDatabase(models.Model):
    """A plugin's own database: its names, its app role's password, and what its node reports.

    Created when the first package with a `database` section is approved, and never deleted
    while the database may exist (PROTECT on both foreign keys). The names come from
    `database_names_for(plugin.identifier)`. `installation_id` marks the roles the node
    creates, so the node refuses roles and databases another installation left behind. The
    app password is stored only encrypted (`tables.services.secrets.secret_encryption`) and
    reaches nothing but the placement's node. The limits are not stored here: they come
    from `plugins.configuration.limits`.
    """

    plugin = models.OneToOneField(Plugin, on_delete=models.PROTECT, related_name="database")
    server = models.ForeignKey(
        PluginDatabaseServer, on_delete=models.PROTECT, related_name="databases"
    )
    installation_id = models.CharField(max_length=32, unique=True)
    database_name = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    owner_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    app_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    job_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    app_password_encrypted = models.TextField()
    state = models.CharField(
        max_length=16, choices=PluginDatabaseState.choices, default=PluginDatabaseState.PENDING
    )
    applied_migrations = models.JSONField(default=list, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=MAX_LAST_ERROR_LENGTH, null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    limits_restored_at = models.DateTimeField(null=True, blank=True)
    # When the last `database_limit_restored` activity event was written, to write at most
    # one an hour.
    limits_restored_event_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["server", name], name=f"plugins_database_server_{name}_uniq"
            )
            for name in ("database_name", "owner_role", "app_role", "job_role")
        ]

    def __str__(self) -> str:
        return f"{self.database_name} on {self.server_id}"
