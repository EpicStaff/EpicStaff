from django.db import models


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
    """

    org = models.OneToOneField(
        "Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="config",
    )
    # EST-3341: free-form retention window for the audit browser. 0
    # (default) = unlimited, per the epic's explicit AC. Query-time filter
    # only in auditor - never deletes underlying session data.
    audit_retention_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "rbac_organization_config"

    def __str__(self) -> str:
        return f"{self.org_id}:config"
