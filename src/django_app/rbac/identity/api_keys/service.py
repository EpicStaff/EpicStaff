from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import Token
from src.shared.models import UserAction
from user_audit.actor import Actor
from user_audit.context import mark_request_handled
from user_audit.recorder import record_user_action

from rbac.access.org_context import OrgContextService
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


def _owner_actor(user) -> Actor:
    return Actor(user_id=user.pk, email=user.email, api_key_name=None)


class ApiKeyService:
    """Self-service CRUD for the caller's own USER keys."""

    @transaction.atomic
    def create_key(
        self, user, org_id: int, name, expires_in_days, session_token: Token | None
    ) -> IssuedKey:
        """Create a USER key for `user`, bound to `org_id`, authorized by `session_token`.

        Locks the owner row first, then re-checks that `session_token` is
        still bound to the owner's current password. Authentication read the
        row without a lock, so a password set committing in between would
        otherwise let the new key slip past `CredentialRevocationService`,
        whose UPDATE only sees keys that exist when it starts. A password
        set locks the user row (password write) before the API keys
        (revocation); this takes them in the same order, so the two cannot
        deadlock. Membership in `org_id` and the active-key cap (per owner and
        org) are checked under the same lock, and the membership row stays
        locked until commit, so a concurrent `remove_member` waits and then
        deletes the new key with the others.

        Raises:
            SessionPasswordChangedError: `session_token` is missing or was
                minted under a previous password, or `user` no longer exists.
            OrgMembershipRequiredError: `user` is not a member of `org_id`
                (superadmins excepted), or the org is inactive.
            OrganizationNotFoundError: a superadmin named an org that does not exist.
            ApiKeyLimitExceededError: `user` already has the maximum number
                of active keys in `org_id`.
        """
        owner = get_user_model().objects.select_for_update().filter(pk=user.pk).first()
        # A user deleted since authentication has no password left to match.
        if (
            owner is None
            or session_token is None
            or not is_bound_to_current_password(session_token, owner)
        ):
            raise SessionPasswordChangedError()

        OrgContextService().assert_membership(user=owner, org_id=org_id, lock=True)

        active = (
            ApiKey.objects.filter(
                created_by=owner,
                org_id=org_id,
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
            org_id=org_id,
            expires_at=expires_at,
        )
        record_user_action(
            action=UserAction.CREATED, org_id=org_id, target=api_key, actor=_owner_actor(owner)
        )
        return IssuedKey(api_key=api_key, raw_key=generated.raw_key)

    def list_keys(self, user):
        return (
            ApiKey.objects.filter(created_by=user, key_type=ApiKey.KeyType.USER)
            .select_related("org")
            .order_by("-created_at")
        )

    def revoke_key(self, user, key_id) -> ApiKey:
        key = self._get_own_key(user, key_id)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
            record_user_action(
                action=UserAction.UPDATED, org_id=key.org_id, target=key, actor=_owner_actor(user)
            )
        else:
            mark_request_handled()
        return key

    def delete_key(self, user, key_id) -> None:
        key = self._get_own_key(user, key_id)
        # Before the delete: the record names the key, and a deleted instance loses its pk.
        record_user_action(
            action=UserAction.DELETED, org_id=key.org_id, target=key, actor=_owner_actor(user)
        )
        key.delete()

    def _get_own_key(self, user, key_id) -> ApiKey:
        key = ApiKey.objects.filter(
            id=key_id, created_by=user, key_type=ApiKey.KeyType.USER
        ).first()
        if key is None:
            raise ApiKeyNotFoundError()
        return key
