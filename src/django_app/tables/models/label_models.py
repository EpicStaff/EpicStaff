from django.db import models
from loguru import logger
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
        db_index=True,
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
        """Returns 'label1/label2/label3' style path.

        Iterative (not recursive) with a `visited` set of ids so a row whose
        parent chain is corrupted into a cycle (self-parent or a loop between
        labels) can't cause a `RecursionError` on every read — this backs
        `__str__` and the serializer's `full_path` field, so it fires on
        every list/retrieve of any label. If a cycle is detected mid-walk,
        the walk stops and returns the partial path built so far instead of
        looping or raising.
        """
        parts = [self.name]
        visited = {self.pk}
        current = self.parent
        while current is not None:
            if current.pk in visited:
                logger.warning(
                    "Label id={} cycle detected: ancestor {} revisited",
                    self.pk,
                    current.pk,
                )
                break
            visited.add(current.pk)
            parts.append(current.name)
            current = current.parent
        return "/".join(reversed(parts))
