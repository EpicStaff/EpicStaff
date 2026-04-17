import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiKey(models.Model):
    name = models.CharField(max_length=255)
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["prefix"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_authenticated(self) -> bool:
        return True

    @staticmethod
    def generate_raw_key() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_key(raw_key: str) -> str:
        secret = (settings.SECRET_KEY or "").encode()
        return hmac.new(secret, raw_key.encode(), hashlib.sha256).hexdigest()

    def set_key(self, raw_key: str) -> None:
        self.prefix = raw_key[:8]
        self.key_hash = self.hash_key(raw_key)

    def check_key(self, raw_key: str) -> bool:
        return hmac.compare_digest(self.key_hash, self.hash_key(raw_key))

    def mark_used(self) -> None:
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])
