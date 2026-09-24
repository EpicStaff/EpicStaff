from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


class SessionInvalidationService:
    """Blacklists every outstanding JWT refresh token for a given user.

    Called by password-recovery flows so that an attacker who still holds
    a valid refresh token after a password compromise cannot continue
    rotating new access tokens. The short-lived access tokens already in
    circulation continue to work until they expire on their own; that is
    accepted as the bound for `ACCESS_TOKEN_LIFETIME` (default 15 min).
    """

    def blacklist_all_for_user(self, user) -> int:
        outstanding = OutstandingToken.objects.filter(user=user)
        count = 0
        for token in outstanding:
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                count += 1
        return count
