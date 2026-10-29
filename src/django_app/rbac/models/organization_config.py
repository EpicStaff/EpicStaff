from django.conf import settings
from django.db import models
from src.shared.retention import DataType, effective_retention_days


class OrganizationConfig(models.Model):
    """Per-organization settings, split from Organization so the core
    identity model (name, active, org boundary) stays lean as more
    settings accumulate over time - a settings table is a well-established
    pattern precisely because moving fields out of a core model later, once
    there's real production data, is far more painful than starting with
    the split.

    Shares its primary key with Organization (1:1 extension table, not a
    separate auto-incrementing id) - every Organization gets exactly one
    OrganizationConfig row, created alongside it in the same transaction
    (see OrganizationManagementService.create_organization).

    Data retention: the `retention_*_days` columns are the organization's own choices of
    how long its data is kept; null means the instance default from
    settings.RETENTION_POLICY. `audit_retention_days` is a different, older setting: how far
    back members may *see* audit events, not how long the events are stored.

    The manager service's nightly purge reads `retention_sessions_days` and
    `retention_conversations_days` directly through SQLAlchemy and applies
    `src.shared.retention.effective_retention_days`, so renaming the table or those columns
    breaks manager as well.
    """

    RETENTION_FIELD_BY_DATA_TYPE = {
        DataType.SESSIONS: "retention_sessions_days",
        DataType.CONVERSATIONS: "retention_conversations_days",
        DataType.AUDIT: "retention_audit_days",
    }

    org = models.OneToOneField(
        "Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="config",
    )
    audit_retention_days = models.PositiveIntegerField(default=0)
    retention_sessions_days = models.PositiveSmallIntegerField(null=True, blank=True)
    retention_conversations_days = models.PositiveSmallIntegerField(null=True, blank=True)
    retention_audit_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Not auto_now: only a retention change stamps it, so editing another setting on this
    # row (such as audit_retention_days) does not look like a retention change.
    retention_updated_at = models.DateTimeField(null=True, blank=True)
    retention_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "rbac_organization_config"

    def __str__(self) -> str:
        return f"{self.org_id}:config"

    def chosen_retention_days(self, data_type: DataType) -> int | None:
        return getattr(self, self.RETENTION_FIELD_BY_DATA_TYPE[data_type])

    def effective_retention_days(self, data_type: DataType) -> int:
        return effective_retention_days(
            self.chosen_retention_days(data_type), settings.RETENTION_POLICY.rules[data_type]
        )
