"""ApiKeyService.create_key re-checks the session's password binding under a
lock on the owner row.

Authentication reads the user row without a lock, so a request can pass it
while a password set is still uncommitted. Without the lock and re-check, the
key it creates would land after the revocation UPDATE and survive the reset.
"""

import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.exceptions import SessionPasswordChangedError
from rbac.identity.api_keys.service import ApiKeyService
from rbac.identity.credential_revocation import CredentialRevocationService
from rbac.identity.passwords.recovery import PasswordRecoveryService
from rbac.models import ApiKey

ORIGINAL_PASSWORD = "UserStrongPass123!"
NEW_PASSWORD = "BrandNewPass456!"
LOCK_WAIT_TIMEOUT_SECONDS = 10


def _create_user(email: str, **extra):
    return get_user_model().objects.create_user(
        email=email, password=ORIGINAL_PASSWORD, **extra
    )


@pytest.mark.django_db
def test_create_key_with_a_bound_session_succeeds():
    owner = _create_user("owner@example.com")
    access = RefreshToken.for_user(owner).access_token

    issued = ApiKeyService().create_key(
        user=owner, name="cli", expires_in_days=None, session_token=access
    )

    assert issued.api_key.created_by_id == owner.pk


@pytest.mark.django_db
def test_create_key_with_a_token_from_a_previous_password_is_rejected():
    """Simulates a request that passed authentication before the password set."""
    owner = _create_user("owner@example.com")
    stale_access = RefreshToken.for_user(owner).access_token
    PasswordRecoveryService().cli_reset(owner.email, NEW_PASSWORD)

    with pytest.raises(SessionPasswordChangedError) as exc_info:
        ApiKeyService().create_key(
            user=owner, name="late", expires_in_days=None, session_token=stale_access
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.get_codes() == "password_changed"
    assert not ApiKey.objects.filter(created_by=owner).exists()


@pytest.mark.django_db
def test_create_key_without_a_session_token_is_rejected():
    owner = _create_user("owner@example.com")

    with pytest.raises(SessionPasswordChangedError):
        ApiKeyService().create_key(
            user=owner, name="no-token", expires_in_days=None, session_token=None
        )

    assert not ApiKey.objects.filter(created_by=owner).exists()


class _RevokerPausingBeforeCommit(CredentialRevocationService):
    """Runs the real revocation, then holds the password transaction open."""

    def __init__(self, revoked: threading.Event, release: threading.Event):
        self._revoked = revoked
        self._release = release

    def revoke_all_credentials_for_user(self, user) -> None:
        super().revoke_all_credentials_for_user(user)
        self._revoked.set()
        assert self._release.wait(LOCK_WAIT_TIMEOUT_SECONDS)


def _waiting_on_a_row_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock'"
        )
        return cursor.fetchone()[0] > 0


@pytest.mark.django_db(transaction=True)
def test_create_key_blocks_on_an_uncommitted_password_set_and_is_then_rejected():
    owner = _create_user("owner@example.com")
    superadmin = _create_user("admin@example.com", is_superadmin=True)
    stale_access = RefreshToken.for_user(owner).access_token
    revoked, release = threading.Event(), threading.Event()
    outcomes: dict[str, object] = {}

    def set_password():
        try:
            PasswordRecoveryService(
                credential_revoker=_RevokerPausingBeforeCommit(revoked, release)
            ).admin_reset(superadmin, owner.pk, NEW_PASSWORD)
        finally:
            connection.close()

    def create_key():
        try:
            ApiKeyService().create_key(
                user=owner, name="racer", expires_in_days=None, session_token=stale_access
            )
            outcomes["create"] = "created"
        except Exception as exc:  # noqa: BLE001 - the outcome is the assertion.
            outcomes["create"] = exc
        finally:
            connection.close()

    password_thread = threading.Thread(target=set_password)
    password_thread.start()
    try:
        # The password write and the revocation are done but not committed:
        # the moment authentication would still see the old hash.
        assert revoked.wait(LOCK_WAIT_TIMEOUT_SECONDS)
        create_thread = threading.Thread(target=create_key)
        create_thread.start()

        deadline = time.monotonic() + LOCK_WAIT_TIMEOUT_SECONDS
        while not _waiting_on_a_row_lock():
            assert create_thread.is_alive(), "create_key finished without waiting for the lock"
            assert time.monotonic() < deadline, "create_key never waited on the user row"
            time.sleep(0.05)
        assert "create" not in outcomes
    finally:
        release.set()
        password_thread.join(LOCK_WAIT_TIMEOUT_SECONDS)

    create_thread.join(LOCK_WAIT_TIMEOUT_SECONDS)
    assert isinstance(outcomes["create"], SessionPasswordChangedError)
    assert not ApiKey.objects.filter(created_by=owner).exists()
