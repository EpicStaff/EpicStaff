from django.conf import settings
from django.db import models

MAX_TARGET_LABEL_LENGTH = 200


class ActivityAction(models.TextChoices):
    API_REQUEST = "api_request"
    PACKAGE_APPROVED = "package_approved"
    GRANT_CREATED = "grant_created"
    INSTALL_HOOK_SUCCEEDED = "install_hook_succeeded"
    INSTALL_HOOK_FAILED = "install_hook_failed"
    INSTALL_HOOK_RETRIED = "install_hook_retried"
    GRANT_SUSPENDED = "grant_suspended"
    GRANT_RESUMED = "grant_resumed"
    SETTINGS_CHANGED = "settings_changed"
    LIMITS_CHANGED = "limits_changed"
    RESTARTED = "restarted"
    DATABASE_READY = "database_ready"
    DATABASE_FAILED = "database_failed"
    DATABASE_LIMIT_RESTORED = "database_limit_restored"


class ActorKind(models.TextChoices):
    PLUGIN = "plugin"
    SUPERADMIN = "superadmin"
    PLATFORM = "platform"


class PluginActivityEvent(models.Model):
    """Something a plugin did in an organization, or something done to a plugin.

    Written for Org Admins and SuperAdmins to read. It names the plugin by identifier and
    the organization by id, never through a foreign key, so events outlive the plugin, its
    grants and its rows; labels are snapshots taken when the event happened. A null
    `organization_id` is a deployment-wide event. `detail` never holds a secret, a setting
    value or a query string.
    """

    plugin_identifier = models.CharField(max_length=32)
    organization_id = models.BigIntegerField(null=True, blank=True)
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_label = models.CharField(max_length=255)
    on_behalf_of_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    on_behalf_of_label = models.CharField(max_length=255, null=True, blank=True)
    action = models.CharField(max_length=32, choices=ActivityAction.choices)
    request_method = models.CharField(max_length=16, null=True, blank=True)
    request_path = models.CharField(max_length=2048, null=True, blank=True)
    request_route = models.CharField(max_length=512, null=True, blank=True)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    target_resource_type = models.CharField(max_length=64, null=True, blank=True)
    target_id = models.CharField(max_length=64, null=True, blank=True)
    target_label = models.CharField(max_length=MAX_TARGET_LABEL_LENGTH, null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Each list reads newest first (`-created_at`, then `-id`), filtered by organization,
        # by plugin, or by both.
        indexes = [
            models.Index(
                fields=["organization_id", "-created_at", "-id"], name="plugins_activity_by_org"
            ),
            models.Index(
                fields=["plugin_identifier", "-created_at", "-id"],
                name="plugins_activity_by_plugin",
            ),
            models.Index(
                fields=["organization_id", "plugin_identifier", "-created_at", "-id"],
                name="plugins_activity_by_org_plugin",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} of {self.plugin_identifier} in org {self.organization_id}"
