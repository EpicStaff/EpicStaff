from typing import get_args

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from src.shared.models.plugin_nodes import MAX_LAST_ERROR_LENGTH, RestoreStep

from plugins.models.enums import BackupReason, PluginDatabaseState, RestoreState
from plugins.models.node import PluginNode
from plugins.models.plugin import Plugin

ONE_OPEN_RESTORE_CONSTRAINT = "plugins_restore_one_open"
OPEN_RESTORE_STATES = (RestoreState.PENDING, RestoreState.RUNNING)
RESTORE_STEP_CHOICES = [(step, step) for step in get_args(RestoreStep)]
# A backup's file name is at most 54 characters (`BACKUP_FILE_NAME_PATTERN`).
BACKUP_FILE_NAME_LENGTH = 64

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
    # No index of its own: the four `(server, ...)` unique constraints lead with it.
    server = models.ForeignKey(
        PluginDatabaseServer, on_delete=models.PROTECT, related_name="databases", db_index=False
    )
    # Unique through a constraint rather than `unique=True`, which would also index it for
    # LIKE queries that nothing makes.
    installation_id = models.CharField(max_length=32)
    database_name = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    owner_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    app_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    job_role = models.CharField(max_length=DATABASE_OBJECT_NAME_LENGTH)
    app_password_encrypted = models.TextField()
    state = models.CharField(
        max_length=16, choices=PluginDatabaseState.choices, default=PluginDatabaseState.PENDING
    )
    applied_migrations = models.JSONField(default=list, blank=True)
    # The ledger with each applied file's sha256 (`{name, sha256}`), as the node last read it,
    # whatever state it reported: an upgrade's Cancel depends on it.
    ledger = models.JSONField(default=list, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=MAX_LAST_ERROR_LENGTH, null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    # When the node last reported it failed, until it reports it ready again: a node goes
    # through `provisioning` on its way back, so the previous state alone would not tell.
    failed_at = models.DateTimeField(null=True, blank=True)
    limits_restored_at = models.DateTimeField(null=True, blank=True)
    # When the last `database_limit_restored` activity event was written, to write at most
    # one an hour.
    limits_restored_event_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["installation_id"], name="plugins_database_installation_id_uniq"
            ),
            *(
                models.UniqueConstraint(
                    fields=["server", name], name=f"plugins_database_server_{name}_uniq"
                )
                for name in ("database_name", "owner_role", "app_role", "job_role")
            ),
        ]

    def __str__(self) -> str:
        return f"{self.database_name} on {self.server_id}"


class PluginDatabaseBackup(models.Model):
    """A backup of a plugin's database that its node took during an upgrade, as it reported it.

    The node holds the file; EpicStaff keeps this record and decides when the node deletes it
    (`plugins.databases.backup_records.backup_retention`). `version` is the plugin version
    whose migrations the database held when it was dumped. `created_at` is the node's clock.
    `deleted_at` is set once the node no longer lists the file. A file the node lists with
    another sha256 than the recorded one is `sha256_mismatch` and never restored.
    `taken_for_version` is the version its upgrade was going to when the backup was recorded
    (a newer version may replace a failed target later); null when that upgrade was not open.
    """

    # No index of its own: the file-name constraint and the retention index lead with it.
    plugin_database = models.ForeignKey(
        PluginDatabase, on_delete=models.CASCADE, related_name="backups", db_index=False
    )
    upgrade = models.ForeignKey(
        "plugins.PluginUpgrade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backups",
    )
    # Which node holds the file; never looked up by it.
    node = models.ForeignKey(
        PluginNode,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
    )
    file_name = models.CharField(max_length=BACKUP_FILE_NAME_LENGTH)
    reason = models.CharField(max_length=16, choices=BackupReason.choices)
    version = models.CharField(max_length=64)
    taken_for_version = models.CharField(max_length=64, null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    sha256_mismatch = models.BooleanField(default=False)
    created_at = models.DateTimeField()
    recorded_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plugin_database", "file_name"], name="plugins_backup_file_uniq"
            ),
        ]
        indexes = [
            # Retention and the backups list read a database's present backups, newest first;
            # retention sorts them by reason itself.
            models.Index(
                fields=["plugin_database", "deleted_at", "created_at"],
                name="plugins_backup_retention",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.file_name} of {self.plugin_database_id}"


class PluginDatabaseRestore(models.Model):
    """A SuperAdmin's request to restore a backup into a plugin's database, and how it went.

    Only during a failed upgrade, from a backup that upgrade took; the node runs it. At most
    one per database is pending or running. `backup_file_name` keeps the file's name after
    the backup's record goes; `pre_restore_backup` is the backup the node took of the database
    just before it was replaced, the way back. `pre_restore_file_name` is its name as the node
    reported it, so the record is linked once a report lists it, also after the restore ended.
    """

    plugin_database = models.ForeignKey(
        PluginDatabase, on_delete=models.CASCADE, related_name="restores"
    )
    upgrade = models.ForeignKey(
        "plugins.PluginUpgrade", on_delete=models.CASCADE, related_name="restores"
    )
    backup = models.ForeignKey(
        PluginDatabaseBackup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    backup_file_name = models.CharField(max_length=BACKUP_FILE_NAME_LENGTH)
    pre_restore_backup = models.ForeignKey(
        PluginDatabaseBackup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pre_restore_file_name = models.CharField(
        max_length=BACKUP_FILE_NAME_LENGTH, null=True, blank=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    state = models.CharField(
        max_length=16, choices=RestoreState.choices, default=RestoreState.PENDING
    )
    step = models.CharField(max_length=16, choices=RESTORE_STEP_CHOICES, null=True, blank=True)
    last_error = models.CharField(max_length=MAX_LAST_ERROR_LENGTH, null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plugin_database"],
                condition=Q(state__in=OPEN_RESTORE_STATES),
                name=ONE_OPEN_RESTORE_CONSTRAINT,
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_RESTORE_STATES

    def __str__(self) -> str:
        return f"restore of {self.backup_file_name} ({self.state})"
