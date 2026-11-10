from django.db import transaction
from django.utils import timezone

from rbac.identity.api_keys.generator import ApiKeyGenerator
from rbac.models import ApiKey

# Placeholder values meaning "no key". Older installs shipped the literal "none"
# as the default, and a key anyone can guess must never authenticate.
_UNSET_KEY_VALUES = frozenset({"", "none"})


class SystemKeyService:
    """Seeds/rotates the singleton system API key from the DJANGO_API_KEY env.

    Invariant: at most ONE active system key exists. Rotation = change the
    env value and restart — the old key is revoked, a new row is created.
    """

    KEY_NAME = "system"

    def seed_from_env(self, raw_key: str | None) -> ApiKey | None:
        """Make the env value the only active system key.

        A blank or "none" value seeds nothing and revokes every active system
        key: unsetting the env must withdraw the key it seeded earlier, not
        leave it live.

        Returns:
            The active system key, or None when the env holds no key.
        """
        if raw_key is None or raw_key.strip().lower() in _UNSET_KEY_VALUES:
            self._revoke_active_keys()
            return None

        key_hash = ApiKeyGenerator.hash_key(raw_key)
        existing = ApiKey.objects.filter(
            key_type=ApiKey.KeyType.SYSTEM,
            key_hash=key_hash,
            revoked_at__isnull=True,
        ).first()
        if existing is not None:
            return existing

        with transaction.atomic():
            self._revoke_active_keys()
            return ApiKey.objects.create(
                name=self.KEY_NAME,
                key_type=ApiKey.KeyType.SYSTEM,
                prefix=ApiKeyGenerator.prefix_of(raw_key),
                key_hash=key_hash,
            )

    @staticmethod
    def _revoke_active_keys() -> int:
        return ApiKey.objects.filter(
            key_type=ApiKey.KeyType.SYSTEM, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
