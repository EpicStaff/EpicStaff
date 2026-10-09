from django.conf import settings
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import TimestampMixin


class AuditFilterPreset(OrgScopedModel, TimestampMixin):
    """
    A user's saved audit-search filter - owner-only (see created_by), never
    shared/visible across users, even to an Org Admin. `filter_body` is the
    auditor search request body (`filters` | `query`, `match_scope`,
    `cursor`, `size`) plus an optional frontend-only `ui_state` (the filters
    panel state), which is never sent to the auditor. Its shape is checked
    in tables/validators/audit_filter_body_validator.py; the filter grammar
    itself is only checked by `auditor` at search time.
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    name = models.CharField(max_length=150)
    filter_body = models.JSONField(default=dict)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "created_by", "name"],
                name="unique_audit_filter_preset_name_per_user",
            ),
        ]

    def __str__(self):
        return self.name
