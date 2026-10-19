from django.conf import settings
from django.db import models
from src.shared.retention import DataType, effective_retention_days


class OrganizationRetention(models.Model):
    """An organization's own retention choices.

    An empty value, or no row at all, means the instance default from
    settings.RETENTION_POLICY. The row is created on the organization's first change.

    The manager service's nightly purge reads this table directly through SQLAlchemy and
    applies `src.shared.retention.effective_retention_days`, so renaming the table or a
    column breaks manager as well.
    """

    FIELD_BY_DATA_TYPE = {
        DataType.SESSIONS: "sessions_days",
        DataType.CONVERSATIONS: "conversations_days",
        DataType.AUDIT: "audit_days",
    }

    org = models.OneToOneField(
        "Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="retention",
    )
    sessions_days = models.PositiveSmallIntegerField(null=True, blank=True)
    conversations_days = models.PositiveSmallIntegerField(null=True, blank=True)
    audit_days = models.PositiveSmallIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )

    class Meta:
        db_table = "rbac_organization_retention"

    def __str__(self) -> str:
        return f"{self.org_id}:retention"

    def chosen_days(self, data_type: DataType) -> int | None:
        return getattr(self, self.FIELD_BY_DATA_TYPE[data_type])

    def effective_days(self, data_type: DataType) -> int:
        return effective_retention_days(
            self.chosen_days(data_type), settings.RETENTION_POLICY.rules[data_type]
        )
