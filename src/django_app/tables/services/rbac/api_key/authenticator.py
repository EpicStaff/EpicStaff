from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from tables.models.rbac_models import ApiKey
from tables.services.rbac.api_key.generator import ApiKeyGenerator
from tables.services.rbac.api_key.principals import PrincipalResolver

MARK_USED_THROTTLE_SECONDS = 60


class ApiKeyAuthenticator:
    """Resolves a raw API key to (principal, ApiKey).

    Exact-match lookup on the unique SHA-256 `key_hash` — one indexed query,
    constant-time by construction. Rejects revoked and expired keys with 401.
    """

    _resolver = PrincipalResolver()

    def authenticate(self, raw_key: str):
        key_hash = ApiKeyGenerator.hash_key(raw_key)
        key = (
            ApiKey.objects.select_related("created_by")
            .filter(key_hash=key_hash, revoked_at__isnull=True)
            .first()
        )
        if key is None:
            raise AuthenticationFailed("Invalid API key")
        if key.is_expired:
            raise AuthenticationFailed("API key has expired")
        self._mark_used(key)
        return self._resolver.resolve(key), key

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
