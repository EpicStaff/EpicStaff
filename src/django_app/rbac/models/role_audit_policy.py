from django.db import models
from django.db.models import CheckConstraint, Q

from rbac.access.audit_history import AUDIT_HISTORY_DAYS_MAX


class RoleAuditPolicy(models.Model):
    """How many days back a role's holders may read audit data.

    No row = unlimited. A row always holds a real limit. Written only through
    `rbac.access.audit_history.sync_audit_policy`.
    """

    role = models.OneToOneField(
        "Role", on_delete=models.CASCADE, primary_key=True, related_name="audit_policy"
    )
    history_days = models.PositiveIntegerField()

    class Meta:
        db_table = "rbac_role_audit_policy"
        constraints = [
            CheckConstraint(
                condition=Q(history_days__gte=1) & Q(history_days__lte=AUDIT_HISTORY_DAYS_MAX),
                name="rbac_role_audit_policy_days_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}: {self.history_days} days"
