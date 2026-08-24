from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ApiKey(models.Model):
    """API key credential. Two classes, discriminated by `key_type`:

    - SYSTEM: singleton seeded from the DJANGO_API_KEY env var; no owner;
      never expires; resolves to SystemServicePrincipal (superadmin) at auth.
    - USER: created via POST /api/profile/api-keys/; owned; inherits the
      owner's live RBAC permissions per X-Organization-Id.

    Crypto/format lives in ApiKeyGenerator — this model stores data only.
    """

    class KeyType(models.TextChoices):
        SYSTEM = "system", "System"
        USER = "user", "User"

    name = models.CharField(max_length=255)
    key_type = models.CharField(
        max_length=8, choices=KeyType.choices, default=KeyType.USER
    )
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(key_type="user", created_by__isnull=False)
                    | Q(
                        key_type="system",
                        created_by__isnull=True,
                        expires_at__isnull=True,
                    )
                ),
                name="api_key_type_invariants",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def status(self) -> str:
        if self.is_revoked:
            return "revoked"
        if self.is_expired:
            return "expired"
        return "active"
