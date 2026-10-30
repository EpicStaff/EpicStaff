from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from rbac.identity.api_keys.generator import ApiKeyGenerator
from rbac.identity.api_keys.principals import PrincipalResolver
from rbac.models import ApiKey, OrganizationUser

MARK_USED_THROTTLE_SECONDS = 60


class ApiKeyAuthenticator:
    """Resolves a raw API key to (principal, ApiKey).

    Exact-match lookup on the unique SHA-256 `key_hash` — one indexed query,
    constant-time by construction. Rejects revoked and expired keys, keys of an
    inactive owner, and USER keys no longer valid for their org (org deactivated,
    or a non-superadmin owner without membership there) with 401. The org check
    lives here because superadmin permission paths never look at the org again.
    """

    _resolver = PrincipalResolver()

    def authenticate(self, raw_key: str):
        key_hash = ApiKeyGenerator.hash_key(raw_key)
        key = (
            ApiKey.objects.select_related("created_by", "org")
            .filter(key_hash=key_hash, revoked_at__isnull=True)
            .first()
        )
        if key is None:
            raise AuthenticationFailed("Invalid API key")
        if key.is_expired:
            raise AuthenticationFailed("API key has expired")
        if key.created_by is not None and not key.created_by.is_active:
            raise AuthenticationFailed("API key owner is inactive")
        if key.key_type == ApiKey.KeyType.USER and not self._valid_for_its_org(key):
            raise AuthenticationFailed("API key is no longer valid for its organization")
        self._mark_used(key)
        return self._resolver.resolve(key), key

    @staticmethod
    def _valid_for_its_org(key: ApiKey) -> bool:
        if not key.org.is_active:
            return False
        return (
            key.created_by.is_superadmin
            or OrganizationUser.objects.filter(
                user_id=key.created_by_id, org_id=key.org_id
            ).exists()
        )

    @staticmethod
    def _mark_used(key: ApiKey) -> None:
        # Throttled: at most one UPDATE per key per window, so hot keys
        # don't turn every request into a row write.
        now = timezone.now()
        if (
            key.last_used_at is not None
            and (now - key.last_used_at).total_seconds() < MARK_USED_THROTTLE_SECONDS
        ):
            return
        key.last_used_at = now
        key.save(update_fields=["last_used_at"])
