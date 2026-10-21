from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import Token

from rbac.exceptions import (
    ApiKeyLimitExceededError,
    ApiKeyNotFoundError,
    SessionPasswordChangedError,
)
from rbac.identity.api_keys.generator import ApiKeyGenerator
from rbac.identity.tokens import is_bound_to_current_password
from rbac.models import ApiKey

MAX_ACTIVE_KEYS = 5


@dataclass
class IssuedKey:
    api_key: ApiKey
    raw_key: str


class ApiKeyService:
    """Self-service CRUD for the caller's own USER keys."""

    @transaction.atomic
    def create_key(self, user, name, expires_in_days, session_token: Token | None) -> IssuedKey:
        """Create a USER key for `user`, authorized by `session_token`.

        Locks the owner row first, then re-checks that `session_token` is
        still bound to the owner's current password. Authentication read the
        row without a lock, so a password set committing in between would
        otherwise let the new key slip past `CredentialRevocationService`,
        whose UPDATE only sees keys that exist when it starts. A password
        set locks the user row (password write) before the API keys
        (revocation); this takes them in the same order, so the two cannot
        deadlock. The active-key cap is counted under the same lock.

        Raises:
            SessionPasswordChangedError: `session_token` is missing or was
                minted under a previous password, or `user` no longer exists.
            ApiKeyLimitExceededError: `user` already has the maximum number
                of active keys.
        """
        owner = get_user_model().objects.select_for_update().filter(pk=user.pk).first()
        # A user deleted since authentication has no password left to match.
        if (
            owner is None
            or session_token is None
            or not is_bound_to_current_password(session_token, owner)
        ):
            raise SessionPasswordChangedError()

        active = (
            ApiKey.objects.filter(
                created_by=owner,
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
            created_by=owner,
            expires_at=expires_at,
        )
        return IssuedKey(api_key=api_key, raw_key=generated.raw_key)

    def list_keys(self, user):
        return ApiKey.objects.filter(created_by=user, key_type=ApiKey.KeyType.USER).order_by(
            "-created_at"
        )

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
