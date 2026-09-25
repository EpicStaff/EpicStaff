from django.conf import settings
from django.db import models

from rbac.models.org_scoped import OrgScopedModel
from tables.models.base_models import TimestampMixin


class AuditFilterPreset(OrgScopedModel, TimestampMixin):
    """
    A user's saved audit-search filter - owner-only (see created_by), never
    shared/visible across users, even to an Org Admin. `filter_body` is the
    exact same {"filters"|"query", "match_scope"} shape the auditor search
    endpoint accepts - opaque JSON here, never parsed/validated in
    django_app (that only happens once, at search time, in `auditor` -
    django_app has no import path to auditor's AST module and isn't meant
    to grow one just for this).
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
