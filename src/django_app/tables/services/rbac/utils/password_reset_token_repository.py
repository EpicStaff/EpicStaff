import hashlib
import secrets
from typing import Optional

from tables.models.rbac_models import PasswordResetToken

# 32 bytes of entropy, URL-safe so it survives a query string.
TOKEN_BYTES = 32


def hash_token(raw_token: str) -> str:
    """Hex-encoded SHA-256 of a raw reset token."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class PasswordResetTokenRepository:
    """Thin data-access gateway around `PasswordResetToken`.

    Keeps the orchestrator free of ORM specifics, and owns the token's storage
    representation: it is the only place that generates a raw token or turns
    one into the hash actually persisted.

    Spending or invalidating a grant deletes its row rather than flagging it,
    so "active" reduces to "exists and has not expired" - callers get either a
    live row or None, and no read path has to filter out spent ones.
    """

    def invalidate_all_for_user(self, user) -> int:
        """Delete every outstanding grant for `user`; returns the row count.

        Only the newest reset link may work, and a deleted row cannot be
        resurrected or accidentally re-read.
        """
        deleted, _ = PasswordResetToken.objects.filter(user=user).delete()
        return deleted

    def create_for_user(self, user) -> tuple[PasswordResetToken, str]:
        """Create a token row and return `(row, raw_token)`.

        The raw token is returned for delivery and never stored - only its
        hash reaches the database.
        """
        raw_token = secrets.token_urlsafe(TOKEN_BYTES)
        row = PasswordResetToken.objects.create(
            user=user, token_hash=hash_token(raw_token)
        )
        return row, raw_token

    def get_active_by_raw_token(self, raw_token: str) -> Optional[PasswordResetToken]:
        """Return the live row matching `raw_token`, else None.

        Hashes the submitted value and matches on `token_hash`, so the lookup
        is a single indexed equality check on the unique column.
        """
        row = (
            PasswordResetToken.objects.select_related("user")
            .filter(token_hash=hash_token(raw_token))
            .first()
        )
        if row is None or row.is_expired():
            return None
        return row

    def consume(self, token: PasswordResetToken) -> None:
        """Spend the grant by deleting it.

        Single-use then holds because the row is gone, not because a flag says
        so - a replay is the same lookup miss as an unknown token.
        """
        token.delete()
