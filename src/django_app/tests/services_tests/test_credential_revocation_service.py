"""CredentialRevocationService and the password-set paths that rely on it.

Every place a password is set must revoke the user's refresh tokens and
personal API keys in the same transaction as the password write, so an
attacker who took over the account keeps no credential past the reset.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.credential_revocation import CredentialRevocationService
from rbac.identity.passwords.change_ticket import PasswordChangeTicketService
from rbac.identity.passwords.recovery import PasswordRecoveryService
from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from rbac.models import ApiKey, PasswordResetToken
from rbac.profile.service import UserProfileService

ORIGINAL_PASSWORD = "UserStrongPass123!"
NEW_PASSWORD = "BrandNewPass456!"


@pytest.fixture
def victim(db):
    return get_user_model().objects.create_user(
        email="victim@example.com", password=ORIGINAL_PASSWORD
    )


@pytest.fixture
def bystander(db):
    return get_user_model().objects.create_user(
        email="bystander@example.com", password=ORIGINAL_PASSWORD
    )


@pytest.fixture
def keys(victim, bystander, issue_api_key):
    """One key of every kind the revocation must or must not touch."""
    already_revoked_at = timezone.now() - timedelta(days=3)
    _, victim_non_expiring = issue_api_key(user=victim, name="non-expiring")
    _, victim_expiring = issue_api_key(
        user=victim, name="expiring", expires_at=timezone.now() + timedelta(days=30)
    )
    _, victim_expired = issue_api_key(
        user=victim, name="expired", expires_at=timezone.now() - timedelta(days=1)
    )
    _, victim_revoked = issue_api_key(
        user=victim, name="revoked", revoked_at=already_revoked_at
    )
    _, bystander_key = issue_api_key(user=bystander, name="bystander")
    _, system_key = issue_api_key(user=None, name="system")
    yield {
        "victim_live": [victim_non_expiring, victim_expiring, victim_expired],
        "victim_revoked": victim_revoked,
        "already_revoked_at": already_revoked_at,
        "bystander": bystander_key,
        "system": system_key,
    }


def _assert_only_victim_keys_revoked(keys) -> None:
    for key in keys["victim_live"]:
        key.refresh_from_db()
        assert key.revoked_at is not None, key.name
    keys["victim_revoked"].refresh_from_db()
    assert keys["victim_revoked"].revoked_at == keys["already_revoked_at"]
    keys["bystander"].refresh_from_db()
    assert keys["bystander"].revoked_at is None
    keys["system"].refresh_from_db()
    assert keys["system"].revoked_at is None


def _assert_nothing_revoked(victim, keys) -> None:
    for key in keys["victim_live"]:
        key.refresh_from_db()
        assert key.revoked_at is None, key.name
    assert not BlacklistedToken.objects.filter(token__user=victim).exists()


# ---- the service itself ----


@pytest.mark.django_db
def test_revoke_all_credentials_revokes_only_the_users_own_keys(victim, keys):
    CredentialRevocationService().revoke_all_credentials_for_user(victim)

    _assert_only_victim_keys_revoked(keys)


@pytest.mark.django_db
def test_revoke_all_credentials_blacklists_only_the_users_refresh_tokens(
    victim, bystander
):
    RefreshToken.for_user(victim)
    RefreshToken.for_user(victim)
    RefreshToken.for_user(bystander)

    CredentialRevocationService().revoke_all_credentials_for_user(victim)

    assert BlacklistedToken.objects.filter(token__user=victim).count() == 2
    assert not BlacklistedToken.objects.filter(token__user=bystander).exists()


@pytest.mark.django_db
def test_revoke_all_credentials_is_idempotent(victim, keys):
    RefreshToken.for_user(victim)
    service = CredentialRevocationService()
    service.revoke_all_credentials_for_user(victim)
    first_revoked_at = {
        key.pk: key.revoked_at for key in ApiKey.objects.filter(created_by=victim)
    }

    service.revoke_all_credentials_for_user(victim)

    assert {
        key.pk: key.revoked_at for key in ApiKey.objects.filter(created_by=victim)
    } == first_revoked_at
    assert BlacklistedToken.objects.filter(token__user=victim).count() == (
        OutstandingToken.objects.filter(user=victim).count()
    )


@pytest.mark.django_db
def test_revoke_all_credentials_skips_expired_refresh_tokens(victim):
    live = RefreshToken.for_user(victim)
    expired = RefreshToken.for_user(victim)
    OutstandingToken.objects.filter(jti=expired["jti"]).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    CredentialRevocationService().revoke_all_credentials_for_user(victim)

    assert BlacklistedToken.objects.filter(token__jti=live["jti"]).exists()
    assert not BlacklistedToken.objects.filter(token__jti=expired["jti"]).exists()


@pytest.mark.django_db
def test_revoke_all_credentials_tolerates_an_already_blacklisted_token(victim):
    already = RefreshToken.for_user(victim)
    already.blacklist()
    live = RefreshToken.for_user(victim)

    CredentialRevocationService().revoke_all_credentials_for_user(victim)

    assert BlacklistedToken.objects.filter(token__jti=already["jti"]).count() == 1
    assert BlacklistedToken.objects.filter(token__jti=live["jti"]).exists()


@pytest.mark.django_db
def test_password_change_confirm_does_not_blacklist_the_fresh_pair(victim):
    old = RefreshToken.for_user(victim)
    ticket, _expires_in = PasswordChangeTicketService().issue(victim)

    fresh_pair = UserProfileService().password_change_confirm(
        victim, ticket, NEW_PASSWORD
    )

    fresh_jti = RefreshToken(fresh_pair.refresh, verify=False)["jti"]
    assert BlacklistedToken.objects.filter(token__jti=old["jti"]).exists()
    assert not BlacklistedToken.objects.filter(token__jti=fresh_jti).exists()


# ---- every password-set path revokes ----


@pytest.mark.django_db
def test_confirm_reset_revokes_the_users_api_keys(victim, keys):
    _token_row, raw_token = PasswordResetTokenRepository().create_for_user(victim)

    PasswordRecoveryService().confirm_reset(raw_token, NEW_PASSWORD)

    _assert_only_victim_keys_revoked(keys)


@pytest.mark.django_db
def test_admin_reset_revokes_the_users_api_keys(victim, keys, superadmin_user):
    PasswordRecoveryService().admin_reset(superadmin_user, victim.pk, NEW_PASSWORD)

    _assert_only_victim_keys_revoked(keys)


@pytest.mark.django_db
def test_cli_reset_revokes_the_users_api_keys(victim, keys):
    PasswordRecoveryService().cli_reset(victim.email, NEW_PASSWORD)

    _assert_only_victim_keys_revoked(keys)


@pytest.mark.django_db
def test_password_change_confirm_revokes_the_users_api_keys(victim, keys):
    ticket, _expires_in = PasswordChangeTicketService().issue(victim)

    UserProfileService().password_change_confirm(victim, ticket, NEW_PASSWORD)

    _assert_only_victim_keys_revoked(keys)


# ---- the password write and the revocation are one transaction ----


class _FailingAfterRevocation(CredentialRevocationService):
    """Does the real revocation, then fails — as a DB error mid-revoke would."""

    def revoke_all_credentials_for_user(self, user) -> None:
        super().revoke_all_credentials_for_user(user)
        raise RuntimeError("revocation failed")


def _run_confirm_reset(victim, _superadmin):
    token_row, raw_token = PasswordResetTokenRepository().create_for_user(victim)
    try:
        PasswordRecoveryService(
            credential_revoker=_FailingAfterRevocation()
        ).confirm_reset(raw_token, NEW_PASSWORD)
    finally:
        # The grant must stay spendable: consuming it rolled back too.
        assert PasswordResetToken.objects.filter(pk=token_row.pk).exists()


def _run_admin_reset(victim, superadmin):
    PasswordRecoveryService(credential_revoker=_FailingAfterRevocation()).admin_reset(
        superadmin, victim.pk, NEW_PASSWORD
    )


def _run_cli_reset(victim, _superadmin):
    PasswordRecoveryService(credential_revoker=_FailingAfterRevocation()).cli_reset(
        victim.email, NEW_PASSWORD
    )


def _run_password_change_confirm(victim, _superadmin):
    ticket, _expires_in = PasswordChangeTicketService().issue(victim)
    UserProfileService(
        credential_revoker=_FailingAfterRevocation()
    ).password_change_confirm(victim, ticket, NEW_PASSWORD)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "run_password_set",
    [
        pytest.param(_run_confirm_reset, id="confirm_reset"),
        pytest.param(_run_admin_reset, id="admin_reset"),
        pytest.param(_run_cli_reset, id="cli_reset"),
        pytest.param(_run_password_change_confirm, id="password_change_confirm"),
    ],
)
def test_failed_revocation_rolls_back_the_password_write(
    victim, keys, superadmin_user, run_password_set
):
    RefreshToken.for_user(victim)

    with pytest.raises(RuntimeError, match="revocation failed"):
        run_password_set(victim, superadmin_user)

    victim.refresh_from_db()
    assert victim.check_password(ORIGINAL_PASSWORD)
    _assert_nothing_revoked(victim, keys)
