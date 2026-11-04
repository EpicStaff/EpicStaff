from django.conf import settings
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import TimestampMixin


class FlowFilterPreset(OrgScopedModel, TimestampMixin):
    """A saved flow-list filter preset, private to its author."""

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
                name="unique_flow_filter_preset_name_per_user",
            ),
        ]

    def __str__(self):
        return self.name
