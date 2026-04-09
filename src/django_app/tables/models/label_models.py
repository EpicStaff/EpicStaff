from django.db import models
from .base_models import MetadataMixin


class Label(MetadataMixin):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "parent"],
                name="unique_label_name_per_level",
            ),
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(parent__isnull=True),
                name="unique_top_level_label_name",
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
