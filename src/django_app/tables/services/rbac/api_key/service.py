from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from tables.models.rbac_models import ApiKey
from tables.services.rbac.api_key.generator import ApiKeyGenerator
from tables.services.rbac.rbac_exceptions import (
    ApiKeyLimitExceededError,
    ApiKeyNotFoundError,
)

MAX_ACTIVE_KEYS = 5


@dataclass
class IssuedKey:
    api_key: ApiKey
    raw_key: str


class ApiKeyService:
    """Self-service CRUD for the caller's own USER keys."""

    def create_key(self, user, name, expires_in_days) -> IssuedKey:
        active = (
            ApiKey.objects.filter(
                created_by=user,
                key_type=ApiKey.KeyType.USER,
                revoked_at__isnull=True,
            )
            .exclude(expires_at__lte=timezone.now())
            .count()
        )
        if active >= MAX_ACTIVE_KEYS:
            raise ApiKeyLimitExceededError()

        generated = ApiKeyGenerator.generate()
        expires_at = (
            timezone.now() + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        )
        api_key = ApiKey.objects.create(
            name=name,
            key_type=ApiKey.KeyType.USER,
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            created_by=user,
            expires_at=expires_at,
        )
        return IssuedKey(api_key=api_key, raw_key=generated.raw_key)

    def list_keys(self, user):
        return ApiKey.objects.filter(
            created_by=user, key_type=ApiKey.KeyType.USER
        ).order_by("-created_at")

    def revoke_key(self, user, key_id) -> ApiKey:
        key = self._get_own_key(user, key_id)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        return key

    def delete_key(self, user, key_id) -> None:
        self._get_own_key(user, key_id).delete()

    def _get_own_key(self, user, key_id) -> ApiKey:
        key = ApiKey.objects.filter(
            id=key_id, created_by=user, key_type=ApiKey.KeyType.USER
        ).first()
        if key is None:
            raise ApiKeyNotFoundError()
        return key
