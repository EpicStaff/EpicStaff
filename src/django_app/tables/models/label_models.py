from django.db import models
from .base_models import MetadataMixin
from tables.models.rbac_models.org_scoped import OrgScopedModel


class Label(OrgScopedModel, MetadataMixin):
    class Scope(models.TextChoices):
        FLOW = "flow", "Flow"
        TOOL = "tool", "Tool"

    name = models.CharField(max_length=100)
    scope = models.CharField(
        max_length=10,
        choices=Scope.choices,
        default=Scope.FLOW,
        help_text="Which independent label tree this label belongs to (Flow labels "
        "and Tool labels never share instances, even with the same name/parent).",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "scope", "name", "parent"],
                name="unique_label_name_per_org_level",
            ),
            models.UniqueConstraint(
                fields=["org", "scope", "name"],
                condition=models.Q(parent__isnull=True),
                name="unique_top_level_label_name_per_org",
            ),
        ]

    def __str__(self):
        return self.full_path

    @property
    def full_path(self):
        """Returns 'label1/label2/label3' style path."""
        if self.parent:
            return f"{self.parent.full_path}/{self.name}"
        return self.name
