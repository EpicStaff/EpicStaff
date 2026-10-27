from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from plugins.models.grant import PluginGrant


class PluginOwnedResource(models.Model):
    """A row a plugin's service account created in an organization.

    Everything the service account creates is owned, on behalf of a person or not; rows a
    person copies or creates are not. The row goes with the organization. Deleting the
    resource leaves the row in place as a tombstone until a periodic sweep removes it: ids are
    never reused, so it never matches another row, and counts read only rows whose resource
    still exists (`existing_owned_resources`). The grant may go first (`grant` is then null):
    the identifier and the organization still say whose resource it was.
    """

    # Neither foreign key gets an index of its own: `(org, plugin_identifier)` and the unique
    # `(content_type, object_id)` lead with them.
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="plugin_owned_resources",
        db_index=False,
    )
    grant = models.ForeignKey(
        PluginGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_resources",
    )
    plugin_identifier = models.CharField(max_length=32)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    object_id = models.BigIntegerField()
    on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"], name="plugins_owned_resource_object_uniq"
            ),
        ]
        indexes = [
            models.Index(
                fields=["org", "plugin_identifier"],
                name="plugins_owned_by_org_plugin",
            ),
            # Rows whose grant is gone refuse every run that uses them, and the run guard
            # asks for them before every run: normally empty, this index answers at once.
            models.Index(
                fields=["org"],
                condition=Q(grant__isnull=True),
                name="plugins_owned_orphan_by_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.content_type_id}:{self.object_id} owned by {self.plugin_identifier}"
