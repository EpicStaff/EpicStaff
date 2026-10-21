from django.db import models
from django.db.models import F, Q

from plugins.models.enums import PlacementHealth, PlacementObservedState, PlacementRemovalState
from plugins.models.plugin import Plugin

MAX_REMOVAL_ERROR_LENGTH = 2000


class PluginNode(models.Model):
    """A machine running plugin backends: the es_plugins service, one process per plugin.

    Deployment-wide. Seeded from the environment at start-up (`seed_plugin_node`). The node
    authenticates with its key, of which only the sha256 is stored; a node that is no longer
    the configured one has no key (`key_hash` null) and cannot authenticate. Each plugin
    process on it gets a port from the port range and a Unix user id from the UID range;
    nothing else on the node's Docker host may use those user ids.
    """

    name = models.CharField(max_length=64, unique=True)
    key_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    internal_host = models.CharField(max_length=255)
    port_range_start = models.PositiveIntegerField()
    port_range_end = models.PositiveIntegerField()
    uid_range_start = models.PositiveIntegerField()
    uid_range_end = models.PositiveIntegerField()
    last_seen_at = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(port_range_start__lte=F("port_range_end")),
                name="plugins_node_port_range_ordered",
            ),
            models.CheckConstraint(
                condition=Q(uid_range_start__lte=F("uid_range_end")),
                name="plugins_node_uid_range_ordered",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PluginPlacement(models.Model):
    """Where a plugin's backend runs, and what its node last reported about the process.

    Created at the first approval of a package with a backend; the port and the Unix user
    id never change for the plugin's life. `restart_generation` and `settings_revision` are
    the desired state's restart triggers: raising either makes the node restart the
    process. The `observed_*` fields, `health` and the rest come from the node's reports.

    Deleting the plugin sets `removal_requested_at`: the node then removes everything it
    keeps for the plugin and reports how it goes (`removal_*`). The row, and with it the port
    and the user id, goes only once the node reports the removal done, so no other plugin
    is given them while anything of this one may be left.
    """

    plugin = models.OneToOneField(Plugin, on_delete=models.CASCADE, related_name="placement")
    node = models.ForeignKey(PluginNode, on_delete=models.PROTECT, related_name="placements")
    port = models.PositiveIntegerField()
    unix_uid = models.PositiveIntegerField()
    restart_generation = models.PositiveIntegerField(default=0)
    settings_revision = models.PositiveIntegerField(default=0)
    observed_state = models.CharField(
        max_length=16,
        choices=PlacementObservedState.choices,
        default=PlacementObservedState.UNKNOWN,
    )
    observed_version = models.CharField(max_length=64, null=True, blank=True)
    health = models.CharField(
        max_length=16, choices=PlacementHealth.choices, default=PlacementHealth.UNKNOWN
    )
    pid = models.PositiveIntegerField(null=True, blank=True)
    restarts = models.PositiveIntegerField(default=0)
    rss_mb = models.FloatField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    log_tail = models.JSONField(default=list, blank=True)
    last_report_at = models.DateTimeField(null=True, blank=True)
    removal_requested_at = models.DateTimeField(null=True, blank=True)
    removal_state = models.CharField(
        max_length=16, choices=PlacementRemovalState.choices, null=True, blank=True
    )
    removal_error = models.CharField(max_length=MAX_REMOVAL_ERROR_LENGTH, null=True, blank=True)
    removal_reported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node", "port"], name="plugins_placement_node_port_uniq"
            ),
            models.UniqueConstraint(
                fields=["node", "unix_uid"], name="plugins_placement_node_uid_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plugin_id} on {self.node_id}:{self.port}"
