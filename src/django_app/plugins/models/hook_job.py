from django.db import models
from django.db.models import Q
from epicstaff_plugin.contracts.hook_api import MAX_HOOK_ERROR_MESSAGE_LENGTH

from plugins.models.grant import PluginGrant
from plugins.models.plugin import Plugin, PluginPackage

ONE_OPEN_JOB_PER_GRANT_AND_KIND_CONSTRAINT = "plugins_hook_job_one_open_per_grant_kind"
# The grant constraint does not cover a job whose grant is gone (NULL), as an organization
# removed job's is once its organization is deleted.
ONE_OPEN_ORG_REMOVED_JOB_CONSTRAINT = "plugins_hook_job_one_open_org_removed"


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
    # Given up on by a SuperAdmin, or by the platform when the plugin is deleted.
    SKIPPED = "skipped"


OPEN_HOOK_JOB_STATES = (HookJobState.PENDING, HookJobState.RUNNING)


class PluginHookJob(models.Model):
    """One lifecycle hook call EpicStaff wants a plugin's backend to make, and how it went.

    The node lists pending jobs in its desired state, claims one (which signs the call),
    calls the plugin and posts the result. A retry puts the same job back to `pending`; its
    `attempt` counts the claims. `timeout_seconds` is fixed at creation from the package's
    manifest. `organization_id` and `organization_name` (the name when the job was created)
    are kept as plain values so the job outlives its grant and its organization: an
    organization removed job runs after the organization is gone. `first_attempt_at` starts
    its retry window, and `next_attempt_at` is when it may be claimed again after a failure.
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
    organization_name = models.CharField(max_length=255, default="", blank=True)
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
    first_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
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
            models.UniqueConstraint(
                fields=["plugin", "organization_id"],
                condition=Q(kind=HookJobKind.ORG_REMOVED, state__in=OPEN_HOOK_JOB_STATES),
                name=ONE_OPEN_ORG_REMOVED_JOB_CONSTRAINT,
            ),
        ]
        indexes = [
            models.Index(
                fields=["plugin", "created_at"],
                condition=Q(state__in=OPEN_HOOK_JOB_STATES),
                name="plugins_hookjob_open_by_plugin",
            ),
            # The scheduled maintenance looks jobs up by kind and state, and the desired state
            # asks which organization removed jobs are due.
            models.Index(
                fields=["kind", "state", "next_attempt_at"], name="plugins_hookjob_kind_state_due"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} hook {self.pk} of {self.plugin_id} in org {self.organization_id}"
