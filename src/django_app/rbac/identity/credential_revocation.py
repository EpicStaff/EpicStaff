from django.utils import timezone
from loguru import logger
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from rbac.models import ApiKey


class CredentialRevocationService:
    """Revokes every long-lived credential a user holds at the moment of the call.

    The single owner of "log this user out everywhere": it blacklists each
    live, not-yet-blacklisted JWT refresh token and revokes each of the
    user's personal (USER) API keys. Called whenever a password is set —
    reset link, admin reset, CLI reset, self-service change — so a refresh
    token or API key obtained with the old password stops working. Also
    called before a user is deleted.

    The SYSTEM key is never touched: it has no owner, so the `created_by`
    filter cannot match it.

    Access tokens, and refresh tokens rotated since login (which have no
    OutstandingToken row), are not handled here: they die through the
    password binding (`CHECK_REVOKE_TOKEN`), which rejects every token minted
    under a previous password hash. Blacklisting refresh tokens here is
    defence in depth on top of that binding.

    Callers should invoke it inside the same `transaction.atomic()` block as
    the password write, so the new password and the revocation commit or roll
    back together.
    """

    def revoke_all_credentials_for_user(self, user) -> None:
        blacklisted_count = self._blacklist_refresh_tokens(user)
        revoked_key_count = self._revoke_api_keys(user)
        logger.info(
            "credentials.revoked_for_user user_id={} refresh_tokens={} api_keys={}",
            user.id,
            blacklisted_count,
            revoked_key_count,
        )

    @staticmethod
    def _blacklist_refresh_tokens(user) -> int:
        # Set-based: a user accumulates one OutstandingToken per login and per
        # rotation, and this runs inside the password transaction. Expired
        # tokens are skipped, since simplejwt already rejects them.
        pending = OutstandingToken.objects.filter(
            user=user,
            expires_at__gt=timezone.now(),
            blacklistedtoken__isnull=True,
        )
        new_entries = [BlacklistedToken(token=token) for token in pending]
        # ignore_conflicts: a concurrent logout or rotation may blacklist the
        # same token between the read above and this insert.
        BlacklistedToken.objects.bulk_create(new_entries, ignore_conflicts=True)
        return len(new_entries)

    @staticmethod
    def _revoke_api_keys(user) -> int:
        # Already-expired keys are revoked too: revocation is the terminal
        # state, so the key stays dead regardless of how expiry is handled now
        # or later.
        return ApiKey.objects.filter(
            created_by=user,
            key_type=ApiKey.KeyType.USER,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())
