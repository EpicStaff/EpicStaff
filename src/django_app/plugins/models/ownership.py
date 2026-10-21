from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models

from plugins.models.grant import PluginGrant


class PluginOwnedResource(models.Model):
    """A row a plugin's service account created in an organization.

    Everything the service account creates is owned, on behalf of a person or not; rows a
    person copies or creates are not. The row goes when the resource is deleted, and with
    the organization. The grant may go first (`grant` is then null): the identifier and the
    organization still say whose resource it was.
    """

    org = models.ForeignKey(
        "rbac.Organization", on_delete=models.CASCADE, related_name="plugin_owned_resources"
    )
    grant = models.ForeignKey(
        PluginGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_resources",
    )
    plugin_identifier = models.CharField(max_length=32)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
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
        ]

    def __str__(self) -> str:
        return f"{self.content_type_id}:{self.object_id} owned by {self.plugin_identifier}"
