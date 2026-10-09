from typing import ClassVar

from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from .base_models import (
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
    soft_delete_consistency_constraint,
)


class Secret(OrgScopedModel, TimestampMixin, MetadataMixin, SoftDeleteMixin):
    """A named, reversibly-encrypted credential owned by one organization.

    `value` holds a Fernet encryptedtext, never the plain text. The plain text
    is produced only by SecretEncryption.decrypt() (tables/services/secrets/
    encryption.py) — this model stores data only.

    In the recycle bin the encrypted value stays until the purge, and the rows
    that use the secret keep their link (soft_delete_keeps_references), so a
    restore brings them back working. SecretResolver reads through `objects`,
    so a binned secret never resolves.
    """

    soft_delete_keeps_references: ClassVar[bool] = True

    name = models.CharField(max_length=128)
    value = models.CharField(max_length=12000, editable=False)
    tail = models.CharField(max_length=4, blank=True, default="", editable=False)

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(active=True),
                name="unique_secret_name_per_org",
            ),
            models.CheckConstraint(condition=~models.Q(value=""), name="secret_value_not_empty"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (org={self.org_id})"
