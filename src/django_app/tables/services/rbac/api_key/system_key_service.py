from django.db import transaction
from django.utils import timezone

from tables.models.rbac_models import ApiKey
from tables.services.rbac.api_key.generator import ApiKeyGenerator


class SystemKeyService:
    """Seeds/rotates the singleton system API key from the DJANGO_API_KEY env.

    Invariant: at most ONE active system key exists. Rotation = change the
    env value and restart — the old key is revoked, a new row is created.
    """

    KEY_NAME = "system"

    def seed_from_env(self, raw_key):
        if not raw_key:
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
            ApiKey.objects.filter(
                key_type=ApiKey.KeyType.SYSTEM, revoked_at__isnull=True
            ).update(revoked_at=timezone.now())
            return ApiKey.objects.create(
                name=self.KEY_NAME,
                key_type=ApiKey.KeyType.SYSTEM,
                prefix=ApiKeyGenerator.prefix_of(raw_key),
                key_hash=key_hash,
            )
