from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ResourceLastEdit(models.Model):
    """The user who made the last real edit of a tracked resource, and when.

    One row per resource, updated in place. `edited_by` is NULL when the edit came from a
    system principal or the editor has since left the organization or been deleted.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    edited_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"], name="unique_last_edit_per_resource"
            )
        ]


class LastEditTrackedModel(models.Model):
    """Abstract model whose rows record their last edit in `ResourceLastEdit`.

    The row is deleted with the resource. Canvas presentation a model declares in
    `last_edit_canvas_fields` (see LastEditTracker) is not an edit of the row.
    """

    last_edits = GenericRelation(
        "rbac.ResourceLastEdit", related_query_name="%(app_label)s_%(class)s"
    )

    class Meta:
        abstract = True

    def records_last_edit(self) -> bool:
        """Return whether edits of this row are recorded; rows shared by every organization are not."""
        return True
