"""Sequential (non-concurrent) service-layer tests for UserManagementService.

These tests cover branches in revoke_superadmin and set_user_active that are
not exercised by the HTTP-layer tests in tests/api_tests/test_rbac_user_management.py.
Plain @pytest.mark.django_db is sufficient here -- no cross-connection
visibility or FOR UPDATE serialization is under test.

What is NOT duplicated here:
  - HTTP permission gates (401/403) -- those belong to the API test suite.
  - Successful revoke when two active superadmins exist -- already covered in
    TestGrantRevokeSuperadmin.test_revoke_when_two_active_superadmins.
  - LastSuperadminError on single-superadmin revoke via the API -- already
    covered in TestLastSuperadminGuard.test_revoke_last_superadmin_400.
"""

import pytest
from django.contrib.auth import get_user_model

from rbac.exceptions import LastSuperadminError, UserNotFoundError
from rbac.governance.users import UserManagementService

UserModel = get_user_model()


@pytest.fixture
def service():
    return UserManagementService()


@pytest.fixture
def active_superadmin(db, django_user_model):
    """One active superadmin -- the system minimum."""
    return django_user_model.objects.create_user(
        email="sa-seq@example.com",
        password="StrongPass123!",
        is_superadmin=True,
        is_active=True,
    )


@pytest.fixture
def second_active_superadmin(db, django_user_model):
    """A second active superadmin to allow demotion of the first."""
    return django_user_model.objects.create_user(
        email="sa-seq-2@example.com",
        password="StrongPass123!",
        is_superadmin=True,
        is_active=True,
    )


@pytest.fixture
def inactive_superadmin(db, django_user_model):
    """A superadmin whose account is deactivated (is_superadmin=True, is_active=False).

    Does NOT count toward the active-superadmin quorum.
    """
    return django_user_model.objects.create_user(
        email="sa-inactive-seq@example.com",
        password="StrongPass123!",
        is_superadmin=True,
        is_active=False,
    )


@pytest.fixture
def plain_user(db, django_user_model):
    """An ordinary user with no superadmin flag."""
    return django_user_model.objects.create_user(
        email="plain-seq@example.com",
        password="StrongPass123!",
        is_superadmin=False,
        is_active=True,
    )


@pytest.mark.django_db
def test_revoke_inactive_superadmin_flips_flag(
    service, active_superadmin, inactive_superadmin
):
    """Revoking an inactive superadmin (is_superadmin=True, is_active=False)
    goes through the else-branch: the target is not in superadmins_map because
    that map only contains is_active=True rows. The guard is not triggered.
    The method still sets is_superadmin=False.

    Precondition: there is at least one active superadmin so the active quorum
    is non-zero, but the target is inactive -- it must not count toward the
    quorum check.
    """
    result = service.revoke_superadmin(
        actor=None, target_user_id=inactive_superadmin.pk
    )

    assert result.pk == inactive_superadmin.pk
    assert result.is_superadmin is False

    inactive_superadmin.refresh_from_db()
    assert inactive_superadmin.is_superadmin is False


@pytest.mark.django_db
def test_revoke_nonexistent_user_raises_user_not_found(service, active_superadmin):
    """revoke_superadmin raises UserNotFoundError for an id that does not
    correspond to any User row. The active_superadmin fixture ensures there is
    at least one active superadmin so the quorum guard is not the binding
    constraint; the not-found path triggers in the else-branch."""
    nonexistent_id = 999_999_999

    with pytest.raises(UserNotFoundError):
        service.revoke_superadmin(actor=None, target_user_id=nonexistent_id)


@pytest.mark.django_db
def test_revoke_non_superadmin_is_idempotent(service, active_superadmin, plain_user):
    """Calling revoke_superadmin on a plain user (is_superadmin=False) returns
    the user without error and leaves is_superadmin False. The target is in the
    else-branch (not in the active-superadmin map); the if target.is_superadmin
    guard short-circuits the write."""
    result = service.revoke_superadmin(actor=None, target_user_id=plain_user.pk)

    assert result.pk == plain_user.pk
    assert result.is_superadmin is False

    plain_user.refresh_from_db()
    assert plain_user.is_superadmin is False


@pytest.mark.django_db
def test_set_user_active_false_flips_is_active(service, active_superadmin, plain_user):
    """Deactivating a plain user (not in the active-superadmin map) succeeds
    without LastSuperadminError and sets is_active=False."""
    result = service.set_user_active(
        actor=None, target_user_id=plain_user.pk, value=False
    )

    assert result.pk == plain_user.pk
    assert result.is_active is False

    plain_user.refresh_from_db()
    assert plain_user.is_active is False


@pytest.mark.django_db
def test_set_user_active_true_flips_is_active(service, active_superadmin, plain_user):
    """Reactivating an inactive plain user succeeds and sets is_active=True."""
    plain_user.is_active = False
    plain_user.save(update_fields=["is_active"])

    result = service.set_user_active(
        actor=None, target_user_id=plain_user.pk, value=True
    )

    assert result.pk == plain_user.pk
    assert result.is_active is True

    plain_user.refresh_from_db()
    assert plain_user.is_active is True


@pytest.mark.django_db
def test_set_user_active_false_on_plain_user_does_not_raise_last_superadmin(
    service, active_superadmin, plain_user
):
    """Deactivating a plain user never raises LastSuperadminError regardless
    of the active-superadmin quorum, because the target is not in the map."""
    # active_superadmin is the only active superadmin; plain_user is not one
    service.set_user_active(actor=None, target_user_id=plain_user.pk, value=False)
    # reaching here without exception is the assertion
