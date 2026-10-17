from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower

from rbac.models.enums import ResourceType

# Product cap: 100 years. 0 = unlimited.
AUDIT_HISTORY_DAYS_MAX = 36_500


class Role(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_built_in = models.BooleanField(default=False)
    # How many days back the role's holders may read audit data; 0 = unlimited.
    # Minted into the audit token as `retention_days` (AuditTokenView).
    audit_history_days = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(AUDIT_HISTORY_DAYS_MAX)]
    )
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
        constraints = [
            UniqueConstraint(
                "org",
                Lower("name"),
                name="rbac_role_org_name_ci_uniq",
            ),
        ]

    def __str__(self) -> str:
        scope = "built-in" if self.is_built_in else f"org={self.org_id}"
        return f"{self.name} ({scope})"


class RolePermission(models.Model):
    role = models.ForeignKey("Role", on_delete=models.CASCADE, related_name="permissions_set")
    resource_type = models.CharField(max_length=32, choices=ResourceType.choices)
    permissions = models.IntegerField(default=0)

    class Meta:
        db_table = "rbac_role_permission"
        unique_together = (("role", "resource_type"),)

    def __str__(self) -> str:
        return f"{self.role_id}:{self.resource_type}={self.permissions}"
