from django.db import models

from tables.models.rbac_models.org_scoped import OrgScopedModel

from .base_models import MetadataMixin, TimestampMixin


class Secret(OrgScopedModel, TimestampMixin, MetadataMixin):
    """A named, reversibly-encrypted credential owned by one organization.

    `value` holds a Fernet encryptedtext, never the plain text. The plain text
    is produced only by SecretEncryption.decrypt() (tables/services/secrets/
    encryption.py) — this model stores data only.
    """

    name = models.CharField(max_length=128)
    value = models.CharField(max_length=12000, editable=False)
    tail = models.CharField(max_length=4, blank=True, default="", editable=False)
    system = models.BooleanField(
        default=False,
        editable=False,
        help_text=(
            "Infrastructure secret (e.g. org-level MinIO credentials) managed "
            "internally by storage_credentials. Never exposed through the "
            "user-facing Secret API."
        ),
    )

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"], name="unique_secret_name_per_org"
            ),
            models.CheckConstraint(
                condition=~models.Q(value=""), name="secret_value_not_empty"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (org={self.org_id})"
