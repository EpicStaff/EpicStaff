"""The rbac governance services announce access-reducing changes through
`org_access_changed` / `user_access_changed`, after commit only.

Each test connects a mock receiver to the signal and asserts the exact
kwargs it got. The tables receiver that forwards to the channel layer is
patched out: what reaches a socket is covered in
tests/graph_collab/test_consumer_org_permission.py.
"""

from dataclasses import dataclass
from functools import partial
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from rbac.exceptions import (
    BuiltInRoleImmutableError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    RoleNotFoundError,
    UserNotFoundError,
)
from rbac.governance.memberships import MembershipManagementService
from rbac.governance.organizations import OrganizationManagementService
from rbac.governance.roles import RoleManagementService
from rbac.governance.users import UserManagementService
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rbac.signals import (
    org_access_changed,
    send_org_access_changed_on_commit,
    send_user_access_changed_on_commit,
    user_access_changed,
)


@pytest.fixture(autouse=True)
def patched_notifier(mocker):
    return mocker.patch("tables.signals.org_access_signals.GraphEditNotifier")


@pytest.fixture
def org_receiver():
    receiver = MagicMock()
    org_access_changed.connect(receiver, weak=False)
    yield receiver
    org_access_changed.disconnect(receiver)


@pytest.fixture
def user_receiver():
    receiver = MagicMock()
    user_access_changed.connect(receiver, weak=False)
    yield receiver
    user_access_changed.disconnect(receiver)


@pytest.fixture
def viewer_role(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def member_role(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="access-signals-org")


def _create_user(email):
    return get_user_model().objects.create_user(email=email, password="StrongPass123!")


@pytest.fixture
def member(org, member_role):
    user = _create_user("access-signals-member@example.com")
    OrganizationUser.objects.create(user=user, org=org, role=member_role)
    return user


@pytest.fixture
def second_member(org, member_role):
    user = _create_user("access-signals-second-member@example.com")
    OrganizationUser.objects.create(user=user, org=org, role=member_role)
    return user


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="access-signals-other-org")


@pytest.fixture
def outsider(other_org, member_role):
    """A member of another organization: no change made in `org` may notify them."""
    user = _create_user("access-signals-outsider@example.com")
    OrganizationUser.objects.create(user=user, org=other_org, role=member_role)
    return user


@pytest.fixture
def custom_role(org):
    role = Role.objects.create(name="access-signals-custom", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.READ | Permission.UPDATE),
    )
    return role


@pytest.fixture
def custom_role_holders(org, custom_role):
    holders = [_create_user(f"access-signals-holder-{index}@example.com") for index in range(2)]
    for holder in holders:
        OrganizationUser.objects.create(user=holder, org=org, role=custom_role)
    return holders


def _membership_id(user, org):
    return OrganizationUser.objects.get(user=user, org=org).id


def _org_calls(receiver):
    return sorted((call.kwargs["user_id"], call.kwargs["org_id"]) for call in receiver.call_args_list)


def _flows_permissions(bitmask):
    return [{"resource_type": ResourceType.FLOWS.value, "bitmask": int(bitmask)}]


# ---- memberships ----


@pytest.mark.django_db
def test_change_role_sends_org_access_changed(
    org_receiver, superadmin_user, member, org, viewer_role, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        MembershipManagementService().change_role(
            actor=superadmin_user,
            membership_id=_membership_id(member, org),
            role_id=viewer_role.id,
        )

    org_receiver.assert_called_once_with(
        signal=org_access_changed,
        sender=MembershipManagementService,
        user_id=member.id,
        org_id=org.id,
    )


@pytest.mark.django_db
def test_change_role_to_the_same_role_sends_nothing(
    org_receiver, superadmin_user, member, org, member_role, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        MembershipManagementService().change_role(
            actor=superadmin_user,
            membership_id=_membership_id(member, org),
            role_id=member_role.id,
        )

    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_remove_member_sends_org_access_changed(
    org_receiver, superadmin_user, member, org, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        MembershipManagementService().remove_member(
            actor=superadmin_user, membership_id=_membership_id(member, org)
        )

    org_receiver.assert_called_once_with(
        signal=org_access_changed,
        sender=MembershipManagementService,
        user_id=member.id,
        org_id=org.id,
    )


@pytest.mark.django_db
def test_add_member_sends_nothing(
    org_receiver, user_receiver, superadmin_user, org, member_role, django_capture_on_commit_callbacks
):
    newcomer = _create_user("access-signals-newcomer@example.com")

    with django_capture_on_commit_callbacks(execute=True):
        MembershipManagementService().add_member(
            actor=superadmin_user,
            org_id=org.id,
            email=None,
            user_id=newcomer.id,
            role_id=member_role.id,
        )

    org_receiver.assert_not_called()
    user_receiver.assert_not_called()


# ---- users ----


@pytest.mark.django_db
def test_revoke_superadmin_sends_user_access_changed(
    user_receiver, org_receiver, superadmin_user, django_capture_on_commit_callbacks
):
    target = get_user_model().objects.create_superuser(
        email="access-signals-second-superadmin@example.com", password="StrongPass123!"
    )

    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().revoke_superadmin(actor=superadmin_user, target_user_id=target.id)

    user_receiver.assert_called_once_with(
        signal=user_access_changed, sender=UserManagementService, user_id=target.id
    )
    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_revoke_superadmin_of_a_non_superadmin_sends_nothing(
    user_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().revoke_superadmin(actor=superadmin_user, target_user_id=member.id)

    user_receiver.assert_not_called()


@pytest.mark.django_db
def test_grant_superadmin_sends_nothing(
    user_receiver, org_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().grant_superadmin(actor=superadmin_user, target_user_id=member.id)

    user_receiver.assert_not_called()
    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_deactivate_user_sends_user_access_changed(
    user_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().set_user_active(
            actor=superadmin_user, target_user_id=member.id, value=False
        )

    user_receiver.assert_called_once_with(
        signal=user_access_changed, sender=UserManagementService, user_id=member.id
    )


@pytest.mark.django_db
def test_deactivate_already_inactive_user_sends_nothing(
    user_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    get_user_model().objects.filter(pk=member.pk).update(is_active=False)

    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().set_user_active(
            actor=superadmin_user, target_user_id=member.id, value=False
        )

    user_receiver.assert_not_called()


@pytest.mark.django_db
def test_reactivate_user_sends_nothing(
    user_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    get_user_model().objects.filter(pk=member.pk).update(is_active=False)

    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().set_user_active(
            actor=superadmin_user, target_user_id=member.id, value=True
        )

    user_receiver.assert_not_called()


@pytest.mark.django_db
def test_delete_user_sends_user_access_changed_with_the_deleted_id(
    user_receiver, superadmin_user, member, django_capture_on_commit_callbacks
):
    member_id = member.id

    with django_capture_on_commit_callbacks(execute=True):
        UserManagementService().delete_user(
            actor=superadmin_user,
            target_user_id=member_id,
            verification_phrase=f"delete-{member.email}",
        )

    user_receiver.assert_called_once_with(
        signal=user_access_changed, sender=UserManagementService, user_id=member_id
    )


# ---- organizations ----


@pytest.mark.django_db
def test_deactivate_organization_signals_exactly_its_members(
    org_receiver,
    default_org,
    org,
    member,
    second_member,
    outsider,
    django_capture_on_commit_callbacks,
):
    """`outsider` belongs to another active org; the exact match proves they are not notified."""
    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().deactivate_organization(org_id=org.id)

    assert _org_calls(org_receiver) == sorted([(member.id, org.id), (second_member.id, org.id)])
    for call in org_receiver.call_args_list:
        assert call.kwargs["sender"] is OrganizationManagementService


@pytest.mark.django_db
def test_deactivate_inactive_organization_sends_nothing(
    org_receiver, default_org, org, member, django_capture_on_commit_callbacks
):
    Organization.objects.filter(pk=org.pk).update(is_active=False)

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().deactivate_organization(org_id=org.id)

    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_reactivate_organization_sends_nothing(
    org_receiver, default_org, org, member, django_capture_on_commit_callbacks
):
    Organization.objects.filter(pk=org.pk).update(is_active=False)

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().reactivate_organization(org_id=org.id)

    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_delete_organization_signals_exactly_its_members(
    org_receiver,
    superadmin_user,
    default_org,
    org,
    member,
    second_member,
    outsider,
    django_capture_on_commit_callbacks,
):
    """`outsider` belongs to another org; the exact match proves they are not notified."""
    org_id = org.id

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(
            actor=superadmin_user, org_id=org_id, verification_phrase=f"delete-{org.name}"
        )

    assert _org_calls(org_receiver) == sorted([(member.id, org_id), (second_member.id, org_id)])
    for call in org_receiver.call_args_list:
        assert call.kwargs["sender"] is OrganizationManagementService


# ---- roles ----


@pytest.mark.django_db
def test_update_role_permissions_signals_exactly_its_holders(
    org_receiver,
    superadmin_user,
    org,
    custom_role,
    custom_role_holders,
    member,
    outsider,
    django_capture_on_commit_callbacks,
):
    """`member` holds a different role in the same org and `outsider` belongs to
    another org; the exact match proves neither is notified."""
    with django_capture_on_commit_callbacks(execute=True):
        RoleManagementService().update_role(
            actor=superadmin_user,
            role_id=custom_role.id,
            changes={"permissions": _flows_permissions(Permission.READ)},
        )

    assert _org_calls(org_receiver) == sorted((holder.id, org.id) for holder in custom_role_holders)
    for call in org_receiver.call_args_list:
        assert call.kwargs["sender"] is RoleManagementService


@pytest.mark.django_db
def test_update_role_without_permissions_sends_nothing(
    org_receiver, superadmin_user, custom_role, custom_role_holders, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        RoleManagementService().update_role(
            actor=superadmin_user,
            role_id=custom_role.id,
            changes={"name": "access-signals-renamed", "description": "renamed"},
        )

    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_create_role_sends_nothing(
    org_receiver, superadmin_user, org, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        RoleManagementService().create_role(
            actor=superadmin_user,
            org_id=org.id,
            name="access-signals-new-role",
            description="d",
            permissions=_flows_permissions(Permission.READ),
        )

    org_receiver.assert_not_called()


@pytest.mark.django_db
def test_delete_role_signals_exactly_its_former_holders(
    org_receiver,
    superadmin_user,
    org,
    custom_role,
    custom_role_holders,
    member,
    outsider,
    django_capture_on_commit_callbacks,
):
    """`member` holds a different role in the same org and `outsider` belongs to
    another org; the exact match proves neither is notified."""
    with django_capture_on_commit_callbacks(execute=True):
        RoleManagementService().delete_role(actor=superadmin_user, role_id=custom_role.id)

    assert _org_calls(org_receiver) == sorted((holder.id, org.id) for holder in custom_role_holders)
    for call in org_receiver.call_args_list:
        assert call.kwargs["sender"] is RoleManagementService


# ---- failing calls ----

_MISSING_ID = 2_000_000_000


@dataclass(frozen=True)
class _Scene:
    actor: object
    org: Organization
    member: object
    custom_role: Role
    viewer_role: Role


def _change_role_to_missing_role(scene):
    return partial(
        MembershipManagementService().change_role,
        actor=scene.actor,
        membership_id=_membership_id(scene.member, scene.org),
        role_id=_MISSING_ID,
    )


def _change_role_on_missing_membership(scene):
    return partial(
        MembershipManagementService().change_role,
        actor=scene.actor,
        membership_id=_MISSING_ID,
        role_id=scene.viewer_role.id,
    )


def _remove_member_twice(scene):
    remove = partial(
        MembershipManagementService().remove_member,
        actor=scene.actor,
        membership_id=_membership_id(scene.member, scene.org),
    )
    remove()
    return remove


def _deactivate_missing_organization(scene):
    return partial(OrganizationManagementService().deactivate_organization, org_id=_MISSING_ID)


def _delete_organization_twice(scene):
    delete = partial(
        OrganizationManagementService().delete_organization,
        actor=scene.actor,
        org_id=scene.org.id,
        verification_phrase=f"delete-{scene.org.name}",
    )
    delete()
    return delete


def _update_built_in_role(scene):
    return partial(
        RoleManagementService().update_role,
        actor=scene.actor,
        role_id=scene.viewer_role.id,
        changes={"permissions": _flows_permissions(Permission.READ)},
    )


def _delete_built_in_role(scene):
    return partial(RoleManagementService().delete_role, actor=scene.actor, role_id=scene.viewer_role.id)


def _delete_role_twice(scene):
    delete = partial(RoleManagementService().delete_role, actor=scene.actor, role_id=scene.custom_role.id)
    delete()
    return delete


def _revoke_superadmin_of_missing_user(scene):
    return partial(
        UserManagementService().revoke_superadmin, actor=scene.actor, target_user_id=_MISSING_ID
    )


def _deactivate_missing_user(scene):
    return partial(
        UserManagementService().set_user_active,
        actor=scene.actor,
        target_user_id=_MISSING_ID,
        value=False,
    )


def _delete_user_twice(scene):
    delete = partial(
        UserManagementService().delete_user,
        actor=scene.actor,
        target_user_id=scene.member.id,
        verification_phrase=f"delete-{scene.member.email}",
    )
    delete()
    return delete


@pytest.mark.parametrize(
    ("arrange_failing_call", "expected_error"),
    [
        pytest.param(_change_role_to_missing_role, RoleNotFoundError, id="change_role-missing-role"),
        pytest.param(
            _change_role_on_missing_membership,
            MembershipNotFoundError,
            id="change_role-missing-membership",
        ),
        pytest.param(_remove_member_twice, MembershipNotFoundError, id="remove_member-twice"),
        pytest.param(
            _deactivate_missing_organization,
            OrganizationNotFoundError,
            id="deactivate_organization-missing-org",
        ),
        pytest.param(
            _delete_organization_twice, OrganizationNotFoundError, id="delete_organization-twice"
        ),
        pytest.param(_update_built_in_role, BuiltInRoleImmutableError, id="update_role-built-in"),
        pytest.param(_delete_built_in_role, BuiltInRoleImmutableError, id="delete_role-built-in"),
        pytest.param(_delete_role_twice, RoleNotFoundError, id="delete_role-twice"),
        pytest.param(
            _revoke_superadmin_of_missing_user,
            UserNotFoundError,
            id="revoke_superadmin-missing-user",
        ),
        pytest.param(_deactivate_missing_user, UserNotFoundError, id="set_user_active-missing-user"),
        pytest.param(_delete_user_twice, UserNotFoundError, id="delete_user-twice"),
    ],
)
@pytest.mark.django_db
def test_failing_governance_call_raises_and_sends_nothing(
    arrange_failing_call,
    expected_error,
    org_receiver,
    user_receiver,
    superadmin_user,
    default_org,
    org,
    member,
    custom_role,
    viewer_role,
    django_capture_on_commit_callbacks,
):
    """The "twice" cases run their first, successful call here, outside the
    capture block, so its own callbacks are never executed: only the failing
    second call is observed."""
    failing_call = arrange_failing_call(
        _Scene(
            actor=superadmin_user,
            org=org,
            member=member,
            custom_role=custom_role,
            viewer_role=viewer_role,
        )
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(expected_error):
            failing_call()

    assert callbacks == []
    org_receiver.assert_not_called()
    user_receiver.assert_not_called()


# ---- after commit only ----


@pytest.mark.django_db(transaction=True)
def test_nothing_is_sent_when_the_transaction_rolls_back(
    org_receiver, superadmin_user, member, org
):
    membership_id = _membership_id(member, org)

    try:
        with transaction.atomic():
            MembershipManagementService().remove_member(
                actor=superadmin_user, membership_id=membership_id
            )
            raise RuntimeError("force a rollback")
    except RuntimeError:
        pass

    org_receiver.assert_not_called()
    assert OrganizationUser.objects.filter(pk=membership_id).exists()


@pytest.mark.django_db
def test_nothing_is_sent_before_commit(
    org_receiver, superadmin_user, member, org, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        MembershipManagementService().remove_member(
            actor=superadmin_user, membership_id=_membership_id(member, org)
        )

    org_receiver.assert_not_called()
    assert len(callbacks) == 1


@pytest.mark.django_db(transaction=True)
def test_a_failing_receiver_neither_undoes_the_write_nor_skips_other_members(
    default_org, org, member, second_member
):
    """`Signal.send` re-raises receiver errors; robust on_commit callbacks log
    them instead, so the committed deactivation stands and the next member's
    callback still runs. Connected first so it fails before `recorder` runs."""

    def failing_receiver(sender, user_id, org_id, **kwargs):
        if user_id == member.id:
            raise RuntimeError("receiver failed")

    recorder = MagicMock()
    org_access_changed.connect(failing_receiver, weak=False)
    org_access_changed.connect(recorder, weak=False)
    try:
        OrganizationManagementService().deactivate_organization(org_id=org.id)
    finally:
        org_access_changed.disconnect(failing_receiver)
        org_access_changed.disconnect(recorder)

    assert Organization.objects.get(pk=org.pk).is_active is False
    assert _org_calls(recorder) == [(second_member.id, org.id)]


# ---- send helpers ----


class _HelperSender:
    pass


@pytest.mark.django_db
def test_send_org_access_changed_on_commit_sends_nothing_before_commit(
    org_receiver, org, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        send_org_access_changed_on_commit(_HelperSender, org.id, [member.id])

    org_receiver.assert_not_called()
    assert len(callbacks) == 1


@pytest.mark.django_db
def test_send_org_access_changed_on_commit_sends_once_per_user_after_commit(
    org_receiver, org, member, second_member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        send_org_access_changed_on_commit(_HelperSender, org.id, [member.id, second_member.id])

    assert org_receiver.call_count == 2
    org_receiver.assert_any_call(
        signal=org_access_changed, sender=_HelperSender, user_id=member.id, org_id=org.id
    )
    org_receiver.assert_any_call(
        signal=org_access_changed, sender=_HelperSender, user_id=second_member.id, org_id=org.id
    )


@pytest.mark.django_db
def test_send_org_access_changed_on_commit_reads_a_lazy_queryset_at_call_time(
    org_receiver, org, member, second_member, django_capture_on_commit_callbacks
):
    memberships = OrganizationUser.objects.filter(org=org)
    lazy_user_ids = memberships.values_list("user_id", flat=True)

    with django_capture_on_commit_callbacks(execute=True):
        send_org_access_changed_on_commit(_HelperSender, org.id, lazy_user_ids)
        memberships.delete()

    assert not OrganizationUser.objects.filter(org=org).exists()
    assert _org_calls(org_receiver) == sorted([(member.id, org.id), (second_member.id, org.id)])


@pytest.mark.django_db
def test_send_org_access_changed_on_commit_with_no_users_sends_nothing(
    org_receiver, org, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        send_org_access_changed_on_commit(_HelperSender, org.id, [])

    org_receiver.assert_not_called()
    assert callbacks == []


@pytest.mark.django_db
def test_send_user_access_changed_on_commit_sends_nothing_before_commit(
    user_receiver, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        send_user_access_changed_on_commit(_HelperSender, member.id)

    user_receiver.assert_not_called()
    assert len(callbacks) == 1


@pytest.mark.django_db
def test_send_user_access_changed_on_commit_sends_once_after_commit(
    user_receiver, org_receiver, member, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        send_user_access_changed_on_commit(_HelperSender, member.id)

    user_receiver.assert_called_once_with(
        signal=user_access_changed, sender=_HelperSender, user_id=member.id
    )
    org_receiver.assert_not_called()
