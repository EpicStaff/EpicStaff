"""rbac's role-assignment checks: other apps' rules run on every membership role assignment."""

import pytest

from rbac.exceptions import PermissionEscalationError
from rbac.governance import role_assignment_checks
from rbac.governance.memberships import MembershipManagementService
from rbac.governance.role_assignment_checks import (
    register_role_assignment_check,
    role_assignment_checks as registered_checks,
)
from rbac.models import OrganizationUser
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class RecordingCheck:
    """Records each call; refuses roles named in `refused`."""

    def __init__(self, refused=()):
        self.calls = []
        self.refused = set(refused)

    def assert_assignable(self, *, effective, role, org_id):
        self.calls.append((role.name, org_id, effective.is_superadmin))
        if role.name in self.refused:
            raise PermissionEscalationError()


@pytest.fixture
def only_check(monkeypatch):
    """Factory → registers one check in place of the app checks for the test's length."""

    def _install(check):
        monkeypatch.setattr(role_assignment_checks, "_checks", [check])
        return check

    return _install


@pytest.fixture
def newcomer(django_user_model):
    return django_user_model.objects.create_user(email="assign-check@example.com", password="StrongPass123!")


@pytest.mark.django_db
def test_adding_a_member_runs_the_checks(only_check, admin_acme, acme, role_member, newcomer):
    check = only_check(RecordingCheck())

    MembershipManagementService().add_member(admin_acme, acme.id, None, newcomer.id, role_member.id)

    assert check.calls == [(role_member.name, acme.id, False)]


@pytest.mark.django_db
def test_a_refusing_check_stops_adding_a_member(only_check, admin_acme, acme, role_member, newcomer):
    only_check(RecordingCheck(refused={role_member.name}))

    with pytest.raises(PermissionEscalationError):
        MembershipManagementService().add_member(admin_acme, acme.id, None, newcomer.id, role_member.id)

    assert not OrganizationUser.objects.filter(user=newcomer).exists()


@pytest.mark.django_db
def test_changing_a_role_runs_the_checks(only_check, admin_acme, acme, role_member, role_viewer, newcomer):
    membership = OrganizationUser.objects.create(user=newcomer, org=acme, role=role_member)
    check = only_check(RecordingCheck(refused={role_viewer.name}))

    with pytest.raises(PermissionEscalationError):
        MembershipManagementService().change_role(admin_acme, membership.id, role_viewer.id)

    membership.refresh_from_db()
    assert membership.role == role_member
    assert check.calls == [(role_viewer.name, acme.id, False)]


@pytest.mark.django_db
def test_the_checks_get_a_superadmin_s_permissions(only_check, superadmin, acme, role_member, newcomer):
    check = only_check(RecordingCheck())

    MembershipManagementService().add_member(superadmin, acme.id, None, newcomer.id, role_member.id)

    assert check.calls == [(role_member.name, acme.id, True)]


def test_a_check_cannot_be_registered_twice(monkeypatch):
    monkeypatch.setattr(role_assignment_checks, "_checks", [])
    register_role_assignment_check(RecordingCheck())

    with pytest.raises(ValueError):
        register_role_assignment_check(RecordingCheck())

    assert len(registered_checks()) == 1
