from django.db import models
from django.db.models import Q
from epicstaff_plugin.contracts.hook_api import MAX_HOOK_ERROR_MESSAGE_LENGTH

from plugins.models.grant import PluginGrant
from plugins.models.plugin import Plugin, PluginPackage

ONE_OPEN_JOB_PER_GRANT_AND_KIND_CONSTRAINT = "plugins_hook_job_one_open_per_grant_kind"


class HookJobKind(models.TextChoices):
    """The lifecycle hooks of `epicstaff_plugin.contracts.hook_api.HookKind`."""

    INSTALL = "install"
    UPGRADE = "upgrade"
    ORG_REMOVED = "org_removed"


class HookJobState(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


OPEN_HOOK_JOB_STATES = (HookJobState.PENDING, HookJobState.RUNNING)


class PluginHookJob(models.Model):
    """One lifecycle hook call EpicStaff wants a plugin's backend to make, and how it went.

    The node lists pending jobs in its desired state, claims one (which signs the call),
    calls the plugin and posts the result. A retry puts the same job back to `pending`; its
    `attempt` counts the claims. `timeout_seconds` is fixed at creation from the package's
    manifest. `organization_id` is kept as a plain id so the job outlives its grant.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="hook_jobs")
    grant = models.ForeignKey(
        PluginGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hook_jobs",
    )
    organization_id = models.BigIntegerField()
    kind = models.CharField(max_length=16, choices=HookJobKind.choices)
    package = models.ForeignKey(
        PluginPackage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    state = models.CharField(
        max_length=16, choices=HookJobState.choices, default=HookJobState.PENDING
    )
    attempt = models.PositiveIntegerField(default=0)
    timeout_seconds = models.PositiveIntegerField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=MAX_HOOK_ERROR_MESSAGE_LENGTH, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["grant", "kind"],
                condition=Q(state__in=OPEN_HOOK_JOB_STATES),
                name=ONE_OPEN_JOB_PER_GRANT_AND_KIND_CONSTRAINT,
            ),
        ]
        indexes = [
            models.Index(
                fields=["plugin", "created_at"],
                condition=Q(state__in=OPEN_HOOK_JOB_STATES),
                name="plugins_hookjob_open_by_plugin",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} hook {self.pk} of {self.plugin_id} in org {self.organization_id}"
