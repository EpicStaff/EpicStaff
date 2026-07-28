from django.db import models

from tables.models.rbac_models.org_scoped import OrgScopedModel

from .base_models import MetadataMixin, TimestampMixin


class Secret(OrgScopedModel, TimestampMixin, MetadataMixin):
    """A named, reversibly-encrypted credential owned by one organization.

    `value` holds a Fernet ciphertext, never plaintext. Plaintext is produced
    only by SecretCipher.open() (tables/services/secrets/cipher.py) — this
    model stores data only.
    """

    name = models.CharField(max_length=128)
    value = models.CharField(max_length=12000, editable=False)
    tail = models.CharField(max_length=4, blank=True, default="", editable=False)

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
