from django.conf import settings
from django.db import models
from django.db.models import Q

from plugins.models.grant import PluginGrant

ROLE_PERMISSION_PER_GRANT_CONSTRAINT = "plugins_role_permission_grant_role_uniq"


class PluginRolePermission(models.Model):
    """The actions a custom role has on one plugin, in the role's organization.

    Keyed by the grant, so actions stored in one organization can never apply in another:
    a custom role belongs to exactly one organization, and the service writes a row only
    for a grant of that organization. Built-in roles are never stored; their actions are
    the manifest's defaults. A role without a row has no actions on the plugin. Deleting the
    role or the grant deletes the row.

    `permissions` is a bitmask of `rbac.models.enums.Permission` bits, as `RolePermission`
    stores them.
    """

    grant = models.ForeignKey(
        PluginGrant, on_delete=models.CASCADE, related_name="role_permissions"
    )
    role = models.ForeignKey("rbac.Role", on_delete=models.CASCADE, related_name="+")
    permissions = models.IntegerField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["grant", "role"], name=ROLE_PERMISSION_PER_GRANT_CONSTRAINT
            ),
            models.CheckConstraint(
                condition=Q(permissions__gt=0), name="plugins_role_permission_not_empty"
            ),
        ]

    def __str__(self) -> str:
        return f"role {self.role_id} on grant {self.grant_id}={self.permissions}"
