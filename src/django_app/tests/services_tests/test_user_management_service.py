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

import threading

import pytest
from django.contrib.auth import get_user_model

from tables.models.graph_models import Graph
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.exceptions import (
    LastSuperadminError,
    SelfAccountDeletionError,
    UserNotFoundError,
)
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


# ---------------------------------------------------------------------------
# delete_user
#
# build_affected_resources unit tests live in test_delete_collector.py --
# it's shared with OrganizationManagementService, not specific to this
# service.
# ---------------------------------------------------------------------------


def test_self_account_deletion_error_shape():
    error = SelfAccountDeletionError()
    assert error.status_code == 400
    assert error.default_code == "cannot_delete_self"


@pytest.fixture
def actor(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="delete-actor@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def target_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="delete-target@x.com", password="StrongPass123!"
    )


@pytest.mark.django_db
def test_delete_user_unknown_id_raises_not_found(db, actor):
    with pytest.raises(UserNotFoundError):
        UserManagementService().preview_delete(
            actor=actor, target_user_id=999999
        )


@pytest.mark.django_db
def test_delete_user_dry_run_deletes_nothing(actor, target_user):
    UserManagementService().preview_delete(
        actor=actor, target_user_id=target_user.pk
    )
    target_user.refresh_from_db()
    assert target_user.pk is not None


@pytest.mark.django_db
def test_delete_user_preview_reports_memberships_and_api_keys(actor, target_user, issue_api_key):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    first_org = Organization.objects.create(name="Preview Membership Org One")
    second_org = Organization.objects.create(name="Preview Membership Org Two")
    OrganizationUser.objects.create(user=target_user, org=first_org, role=role)
    OrganizationUser.objects.create(user=target_user, org=second_org, role=role)
    issue_api_key(user=target_user, name="preview-key")

    preview = UserManagementService().preview_delete(
        actor=actor, target_user_id=target_user.pk
    )

    assert preview.affected_resources["memberships"] == 2
    assert preview.affected_resources["api_keys"] == 1


@pytest.mark.django_db
def test_delete_user_preview_omits_memberships_and_api_keys_when_the_user_has_none(
    actor, target_user
):
    preview = UserManagementService().preview_delete(
        actor=actor, target_user_id=target_user.pk
    )

    assert "memberships" not in preview.affected_resources
    assert "api_keys" not in preview.affected_resources


@pytest.mark.django_db
def test_delete_user_dry_run_prediction_matches_what_the_delete_actually_removes(
    actor, target_user, issue_api_key, settings, tmp_path
):
    """The load-bearing guarantee: the delete removes exactly the rows the preview predicted, and nothing else."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    org = Organization.objects.create(name="Cross-check Membership Org")
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=target_user, org=org, role=role)
    issue_api_key(user=target_user, name="cross-check-key")
    settings.MEDIA_ROOT = str(tmp_path)
    target_user.avatar.save(
        "face.png", SimpleUploadedFile("face.png", b"fake-image-bytes"), save=True
    )

    service = UserManagementService()
    preview = service.preview_delete(actor=actor, target_user_id=target_user.pk)
    actual = service.delete_user(actor=actor, target_user_id=target_user.pk)

    assert preview.affected_resources == actual.affected_resources


@pytest.mark.django_db
def test_delete_user_report_passes_through_the_documented_serializer(actor, target_user):
    """UserDeleteReportSerializer must accept the real preview_delete output, not just a hand-written fixture."""
    import dataclasses

    from rbac.serializers.delete import UserDeleteReportSerializer

    report = UserManagementService().preview_delete(
        actor=actor, target_user_id=target_user.pk
    )

    serializer = UserDeleteReportSerializer(data=dataclasses.asdict(report))
    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_delete_user_report_is_stable_across_calls(actor, target_user):
    """Two service calls against the same target report an identical affected_resources block."""
    # Enriched with a real outstanding refresh token, minted the same way
    # `test_deleting_a_user_blacklists_their_refresh_tokens` does, so this
    # exercises the same `blacklist_all_for_user` path the reports must agree
    # across.
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(target_user)

    service = UserManagementService()
    preview = service.preview_delete(actor=actor, target_user_id=target_user.pk)
    actual = service.delete_user(actor=actor, target_user_id=target_user.pk)
    assert preview.affected_resources == actual.affected_resources


@pytest.mark.django_db
def test_real_delete_removes_the_user(actor, target_user, django_user_model):
    UserManagementService().delete_user(
        actor=actor, target_user_id=target_user.pk
    )
    assert not django_user_model.objects.filter(pk=target_user.pk).exists()


@pytest.mark.django_db
def test_deleting_a_user_preserves_their_authored_content(actor, target_user):
    org = Organization.objects.create(name="Authored Org")
    graph = Graph.objects.create(name="kept", org=org, created_by=target_user)

    UserManagementService().delete_user(
        actor=actor, target_user_id=target_user.pk
    )

    graph.refresh_from_db()
    assert graph.created_by is None


@pytest.mark.django_db
def test_deleting_a_user_removes_their_memberships(actor, target_user):
    org = Organization.objects.create(name="Membership Org")
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=target_user, org=org, role=role)

    UserManagementService().delete_user(
        actor=actor, target_user_id=target_user.pk
    )

    assert not OrganizationUser.objects.filter(org=org).exists()


@pytest.mark.django_db
def test_cannot_delete_self(actor):
    with pytest.raises(SelfAccountDeletionError):
        UserManagementService().preview_delete(actor=actor, target_user_id=actor.pk)


@pytest.mark.django_db
def test_cannot_delete_self_in_real_mode_too(actor):
    """The self-deletion guard applies whether or not dry_run is set."""
    with pytest.raises(SelfAccountDeletionError):
        UserManagementService().delete_user(actor=actor, target_user_id=actor.pk)


@pytest.mark.django_db
def test_cannot_delete_the_last_superadmin(db, django_user_model, actor):
    other_actor = django_user_model.objects.create_user(
        email="delete-other@x.com", password="StrongPass123!"
    )
    other_actor.is_superadmin = True
    other_actor.save(update_fields=["is_superadmin"])
    # `actor` is the only OTHER superadmin; remove it so the target is last.
    django_user_model.objects.filter(pk=actor.pk).update(is_superadmin=False)

    with pytest.raises(LastSuperadminError):
        UserManagementService().preview_delete(
            actor=actor, target_user_id=other_actor.pk
        )


@pytest.mark.django_db
def test_deleting_a_user_blacklists_their_refresh_tokens(actor, target_user):
    """Access tokens outlive the row by up to 15 min; refresh must not."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(target_user)
    token_ids = list(
        OutstandingToken.objects.filter(user=target_user).values_list("id", flat=True)
    )
    assert token_ids, "fixture failed to mint an outstanding token"

    UserManagementService().delete_user(
        actor=actor, target_user_id=target_user.pk
    )

    assert BlacklistedToken.objects.filter(token_id__in=token_ids).count() == len(token_ids)


@pytest.mark.django_db
def test_delete_user_locked_recheck_takes_a_lock_on_the_target_row_even_when_not_a_superadmin(
    db, actor, target_user, mocker
):
    """delete_user's locked recheck always issues a locking query on the target's own row, not just when it's already flagged superadmin."""
    from tables.models.user import User

    mock_select_for_update = mocker.patch.object(User.objects, "select_for_update")
    mock_select_for_update.return_value.get.return_value = target_user
    try:
        UserManagementService().delete_user(
            actor=actor, target_user_id=target_user.pk
        )
    except Exception:
        pass
    assert mock_select_for_update.called, (
        "delete_user's locked recheck must always take a lock on the target's own "
        "row, even when instance.is_superadmin is False at the unlocked read"
    )


@pytest.mark.django_db
def test_user_avatar_is_previewed_and_removed_from_disk(
    actor, target_user, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The avatar lives on local disk, not in MinIO: the report names it and the real delete removes the file."""
    from pathlib import Path

    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = str(tmp_path)
    target_user.avatar.save(
        "face.png", SimpleUploadedFile("face.png", b"fake-image-bytes"), save=True
    )
    avatar_name = target_user.avatar.name
    stored = Path(settings.MEDIA_ROOT) / avatar_name
    assert stored.exists(), "fixture failed to write the avatar"

    service = UserManagementService()
    preview = service.preview_delete(actor=actor, target_user_id=target_user.pk)
    assert preview.affected_resources["avatar"] == 1
    assert stored.exists(), "a dry run must not touch the file"

    with django_capture_on_commit_callbacks(execute=True):
        service.delete_user(actor=actor, target_user_id=target_user.pk)

    assert not stored.exists()


@pytest.mark.django_db
def test_avatar_cleanup_failure_does_not_undo_a_committed_delete(
    actor, target_user, django_user_model, settings, tmp_path, mocker, django_capture_on_commit_callbacks
):
    """A storage failure while deleting the orphaned avatar is logged, never re-raised, and never undoes the already-committed delete."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = str(tmp_path)
    target_user.avatar.save(
        "face.png", SimpleUploadedFile("face.png", b"fake-image-bytes"), save=True
    )
    mocker.patch.object(
        target_user.avatar.storage, "delete", side_effect=RuntimeError("storage unavailable")
    )

    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().delete_user(
            actor=actor, target_user_id=target_user.pk
        )

    assert not django_user_model.objects.filter(pk=target_user.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_delete_user_registers_cleanup_via_on_commit_not_synchronously(
    actor, target_user, mocker
):
    """delete_user's real on_commit(...) call is what defers _cleanup_user_delete_external, not a direct call."""
    mock_on_commit = mocker.patch(
        "rbac.governance.users.transaction.on_commit"
    )
    UserManagementService().delete_user(
        actor=actor, target_user_id=target_user.pk
    )
    mock_on_commit.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_on_commit_callback_does_not_fire_if_the_enclosing_transaction_rolls_back(
    actor, target_user, mocker
):
    """A cleanup callback registered via delete_user's on_commit before an enclosing rollback never fires."""
    from django.db import transaction as dj_transaction

    mock_cleanup = mocker.patch.object(UserManagementService, "_cleanup_user_delete_external")

    with pytest.raises(RuntimeError):
        with dj_transaction.atomic():
            UserManagementService().delete_user(
                actor=actor, target_user_id=target_user.pk
            )
            raise RuntimeError("force a rollback after on_commit was registered")

    mock_cleanup.assert_not_called()
