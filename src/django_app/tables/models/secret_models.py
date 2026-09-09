from django.db import models
from django.db.models import Q

from tables.models.rbac_models.org_scoped import OrgScopedModel

from .base_models import MetadataMixin, TimestampMixin


class SecretManager(models.Manager):
    """Default manager for `Secret` — excludes internal `system=True` rows.

    System secrets (e.g. org-level MinIO admin credentials) must never be
    reachable through user-facing code paths (resolver, serializers,
    viewsets). Use `Secret.all_objects` for the small set of infrastructure
    call sites that legitimately need `system=True` rows.
    """

    def get_queryset(self):
        return super().get_queryset().filter(system=False)


class Secret(OrgScopedModel, TimestampMixin, MetadataMixin):
    """A named, reversibly-encrypted credential owned by one organization.

    `value` holds a Fernet encryptedtext, never the plain text. The plain text
    is produced only by SecretEncryption.decrypt() (tables/services/secrets/
    encryption.py) — this model stores data only.

    Several models FK to `Secret` (LLM/embedding config API keys, MCP,
    realtime agent config, webhook triggers, etc.). Forward FK access on a
    single related object (e.g. `some_config.api_key_secret`) resolves by
    direct pk lookup and bypasses both `objects` and `all_objects` — no
    manager filtering applies there. So the `system=False` protection is
    enforced only at the serializer layer, by scoping every FK field's
    `PrimaryKeyRelatedField`/`OrgScopedPrimaryKeyRelatedField` queryset to
    `Secret.objects` (never `all_objects`). Keep this in mind when adding a
    new FK to `Secret` or a serializer field that lets a client set one.
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

    objects = SecretManager()
    all_objects = models.Manager()

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=Q(system=False),
                name="unique_secret_name_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=Q(system=True),
                name="unique_system_secret_name_per_org",
            ),
            models.CheckConstraint(
                condition=~models.Q(value=""), name="secret_value_not_empty"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (org={self.org_id})"
