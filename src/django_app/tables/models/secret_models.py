from typing import ClassVar

from django.db import models
from django.db.models import Q
from rbac.models.last_edit import LastEditTrackedModel
from rbac.models.org_scoped import OrgScopedModel

from .base_models import (
    MetadataMixin,
    SoftDeleteMixin,
    TimestampMixin,
    soft_delete_consistency_constraint,
)


class Secret(OrgScopedModel, LastEditTrackedModel, TimestampMixin, MetadataMixin, SoftDeleteMixin):
    """A named, reversibly-encrypted credential owned by one organization.

    `value` holds a Fernet encryptedtext, never the plain text. The plain text
    is produced only by SecretEncryption.decrypt() (tables/services/secrets/
    encryption.py) — this model stores data only.

    In the recycle bin the encrypted value stays until the purge, and the rows
    that use the secret keep their link (soft_delete_keeps_references), so a
    restore brings them back working. Its last edit is who moved it to the bin
    (a secret is never edited: name and value are immutable). SecretResolver
    reads through `objects`, so a binned secret never resolves.

    `system=True` rows (e.g. org-level storage admin credentials) are internal to
    storage_credentials: they are `internal_rows`, so `objects` and
    `deleted_objects` never return them and they never reach the recycle bin.
    Infrastructure code that needs them reads `all_objects`.

    Several models FK to `Secret` (LLM/embedding config API keys, MCP,
    realtime agent config, webhook triggers, etc.). Forward FK access on a
    single related object (e.g. `some_config.api_key_secret`) resolves by
    direct pk lookup and bypasses both `objects` and `all_objects` — no
    manager filtering applies there. So the `system=False` protection is
    enforced only at the serializer layer: every FK field's queryset is
    `Secret.objects` (never `all_objects`), or a KeptLinkPrimaryKeyRelatedField,
    which leaves out `internal_rows` too. Keep this in mind when adding a
    new FK to `Secret` or a serializer field that lets a client set one.
    """

    soft_delete_keeps_references: ClassVar[bool] = True
    internal_rows: ClassVar[Q] = Q(system=True)

    name = models.CharField(max_length=128)
    value = models.CharField(max_length=12000, editable=False)
    tail = models.CharField(max_length=4, blank=True, default="", editable=False)
    system = models.BooleanField(
        default=False,
        editable=False,
        help_text=(
            "Infrastructure secret (e.g. org-level storage credentials) managed "
            "internally by storage_credentials. Never exposed through the "
            "user-facing Secret API."
        ),
    )

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            # A binned name is free again; system names are unique on their own.
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=Q(active=True, system=False),
                name="unique_secret_name_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=Q(system=True),
                name="unique_system_secret_name_per_org",
            ),
            models.CheckConstraint(condition=~models.Q(value=""), name="secret_value_not_empty"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (org={self.org_id})"
