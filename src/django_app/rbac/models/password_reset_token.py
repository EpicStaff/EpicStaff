from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class PasswordResetToken(models.Model):
    """A single-use, TTL-bound password-reset grant.

    Two invariants shape this model:

    **Only the hash is stored, never the token.** A read of this table -- from
    a leaked backup, a replica, or a query log -- is therefore not replayable
    against the confirm endpoint: the row holds a verifier, not the secret.
    Generation and hashing live in `PasswordResetTokenRepository`, the only
    place that ever handles the raw value.

    **The row's existence *is* the grant.** Consuming a reset deletes the row,
    and requesting a new one deletes any earlier rows for that user. There is
    no `is_used` flag to keep in sync, no accumulation of spent verifiers, and
    no read path that has to remember to filter them out -- a spent token and
    an unknown one are the same lookup miss, which is also exactly the answer
    the confirm endpoint gives.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rbac_password_reset_token"

    def is_expired(self) -> bool:
        ttl_seconds = getattr(settings, "PASSWORD_RESET_TOKEN_TTL", 3600)
        return timezone.now() > self.created_at + timedelta(seconds=ttl_seconds)

    def __str__(self) -> str:
        # Deliberately omits token_hash: __str__ output reaches logs and debug
        # surfaces, and the hash is still the value a lookup matches on.
        return f"reset grant for user={self.user_id}"
