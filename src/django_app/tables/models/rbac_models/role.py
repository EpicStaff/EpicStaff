from django.db import models

from tables.models.rbac_models.rbac_enums import ResourceType


class Role(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_built_in = models.BooleanField(default=False)
    org = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="roles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rbac_role"

    def __str__(self) -> str:
        scope = "built-in" if self.is_built_in else f"org={self.org_id}"
        return f"{self.name} ({scope})"


class RolePermission(models.Model):
    role = models.ForeignKey(
        "Role", on_delete=models.CASCADE, related_name="permissions_set"
    )
    resource_type = models.CharField(max_length=32, choices=ResourceType.choices)
    permissions = models.IntegerField(default=0)

    class Meta:
        db_table = "rbac_role_permission"
        unique_together = (("role", "resource_type"),)

    def __str__(self) -> str:
        return f"{self.role_id}:{self.resource_type}={self.permissions}"
