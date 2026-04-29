import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class PasswordResetToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    token = models.UUIDField(default=uuid.uuid4, db_index=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rbac_password_reset_token"

    def is_expired(self) -> bool:
        ttl_seconds = getattr(settings, "PASSWORD_RESET_TOKEN_TTL", 3600)
        return timezone.now() > self.created_at + timedelta(seconds=ttl_seconds)

    def __str__(self) -> str:
        return f"token={self.token} user={self.user_id} used={self.is_used}"
