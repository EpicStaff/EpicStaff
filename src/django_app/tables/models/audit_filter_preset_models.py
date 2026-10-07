from django.conf import settings
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import TimestampMixin


class AuditFilterPreset(OrgScopedModel, TimestampMixin):
    """
    A saved audit-search filter, shared within its organization: every member
    with AUDIT:read can see, export and duplicate it, but only its author
    (`created_by`) can edit or delete it. Names are unique per org. `filter_body` is the
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
                fields=["org", "name"],
                name="unique_audit_filter_preset_name_per_org",
            ),
        ]

    def __str__(self):
        return self.name
