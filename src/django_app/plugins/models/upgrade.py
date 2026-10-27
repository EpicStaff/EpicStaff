from typing import get_args

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from src.shared.models.plugin_nodes import MAX_LAST_ERROR_LENGTH, UpgradeStep

from plugins.models.enums import UpgradeStage
from plugins.models.plugin import Plugin, PluginPackage

ONE_OPEN_UPGRADE_CONSTRAINT = "plugins_upgrade_one_open"
OPEN_UPGRADE_STAGES = (UpgradeStage.PREPARING, UpgradeStage.MAINTENANCE, UpgradeStage.MIGRATING)
# The stages in which the plugin node runs the upgrade's target rather than the current package.
TARGET_STAGES = (UpgradeStage.MAINTENANCE, UpgradeStage.MIGRATING)
UPGRADE_STEP_CHOICES = [(step, step) for step in get_args(UpgradeStep)]


class PluginUpgrade(models.Model):
    """One upgrade of a plugin to a newer approved package, from its approval to its end.

    At most one per plugin is open (`preparing`, `maintenance` or `migrating`); the SuperAdmin
    starts it by approving the newer package. The plugin keeps running while its node prepares
    the target, and is stopped only once the node asks for `maintenance`. `failed_at` and
    `last_error` are set when the node reports a failure, which leaves the upgrade in its
    stage until a Retry, a newer version or a Cancel. `backup` is the backup taken before this
    upgrade's first migration; `backup_required` says one is needed. `ledger_at_migrations` is
    the database's ledger (`{name, sha256}` each) as EpicStaff knew it when the node first
    asked to run the migrations: what the database held before any migration of the upgrade,
    which `database_changed` compares with. The versions are kept as text so the history
    outlives the packages, which are deleted once the upgrade is over.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="upgrades")
    from_package = models.ForeignKey(
        PluginPackage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_package = models.ForeignKey(
        PluginPackage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    from_version = models.CharField(max_length=64)
    to_version = models.CharField(max_length=64)
    stage = models.CharField(max_length=16, choices=UpgradeStage.choices)
    step = models.CharField(max_length=16, choices=UPGRADE_STEP_CHOICES, null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=MAX_LAST_ERROR_LENGTH, null=True, blank=True)
    backup_required = models.BooleanField(default=False)
    backup = models.ForeignKey(
        "plugins.PluginDatabaseBackup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    adds_backend = models.BooleanField(default=False)
    access_growth_acknowledged = models.BooleanField(default=False)
    untrusted_acknowledged = models.BooleanField(default=False)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(default=timezone.now)
    maintenance_started_at = models.DateTimeField(null=True, blank=True)
    migrations_started_at = models.DateTimeField(null=True, blank=True)
    # None until the first `advance` to migrations, and always for an upgrade that adds a backend.
    ledger_at_migrations = models.JSONField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plugin"],
                condition=Q(stage__in=OPEN_UPGRADE_STAGES),
                name=ONE_OPEN_UPGRADE_CONSTRAINT,
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.stage in OPEN_UPGRADE_STAGES

    @property
    def failed(self) -> bool:
        return self.failed_at is not None

    def __str__(self) -> str:
        return f"upgrade of {self.plugin_id} to {self.to_version} ({self.stage})"
