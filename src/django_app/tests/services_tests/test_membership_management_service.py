import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import OrganizationUser
from tables.services.rbac.membership_management_service import (
    MembershipManagementService,
)
from tables.services.rbac.rbac_exceptions import (
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    SelfMembershipModificationError,
    UserNotFoundError,
)

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

svc = MembershipManagementService()


# ---- list ----


@pytest.mark.django_db
def test_list_scoped_to_readable_orgs(
    admin_acme, acme, beta, django_user_model, role_member
):
    OrganizationUser.objects.create(
        user=django_user_model.objects.create_user(
            email="b@x.com", password="StrongPass123!"
        ),
        org=beta,
        role=role_member,
    )
    ids = {m.org_id for m in svc.list_memberships(actor=admin_acme, org_ids=None)}
    assert ids == {acme.id}  # not beta


@pytest.mark.django_db
def test_list_forbidden_org_ids_fails_loud(admin_acme, beta):
    with pytest.raises(PermissionDenied):
        list(svc.list_memberships(actor=admin_acme, org_ids=[beta.id]))


@pytest.mark.django_db
def test_list_filters_by_role_and_status(
    admin_acme, acme, role_member, django_user_model
):
    inactive = django_user_model.objects.create_user(
        email="inact@x.com", password="StrongPass123!", is_active=False
    )
    OrganizationUser.objects.create(user=inactive, org=acme, role=role_member)
    members = list(
        svc.list_memberships(actor=admin_acme, org_ids=None, role_id=role_member.id)
    )
    assert {m.user_id for m in members} == {inactive.id}
    active = list(
        svc.list_memberships(actor=admin_acme, org_ids=None, status_value="active")
    )
    assert inactive.id not in {m.user_id for m in active}


# ---- add ----


@pytest.mark.django_db
def test_add_existing_member_by_email(admin_acme, acme, role_member, django_user_model):
    target = django_user_model.objects.create_user(
        email="new@x.com", password="StrongPass123!"
    )
    m = svc.add_member(
        actor=admin_acme,
        org_id=acme.id,
        email="new@x.com",
        user_id=None,
        role_id=role_member.id,
    )
    assert (
        m.user_id == target.id and m.org_id == acme.id and m.role_id == role_member.id
    )


@pytest.mark.django_db
def test_add_existing_member_by_user_id(
    admin_acme, acme, role_member, django_user_model
):
    target = django_user_model.objects.create_user(
        email="byid@x.com", password="StrongPass123!"
    )
    m = svc.add_member(
        actor=admin_acme,
        org_id=acme.id,
        email=None,
        user_id=target.id,
        role_id=role_member.id,
    )
    assert m.user_id == target.id


@pytest.mark.django_db
def test_add_unknown_email_raises_user_not_found(admin_acme, acme, role_member):
    with pytest.raises(UserNotFoundError):
        svc.add_member(
            actor=admin_acme,
            org_id=acme.id,
            email="nobody@x.com",
            user_id=None,
            role_id=role_member.id,
        )


@pytest.mark.django_db
def test_add_duplicate_membership_raises(
    admin_acme, acme, role_member, django_user_model
):
    target = django_user_model.objects.create_user(
        email="dup@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=target, org=acme, role=role_member)
    with pytest.raises(MembershipAlreadyExistsError):
        svc.add_member(
            actor=admin_acme,
            org_id=acme.id,
            email="dup@x.com",
            user_id=None,
            role_id=role_member.id,
        )


@pytest.mark.django_db
def test_add_denied_without_users_create(
    member_only, acme, role_member, django_user_model
):
    django_user_model.objects.create_user(email="t@x.com", password="StrongPass123!")
    with pytest.raises(PermissionDenied):
        svc.add_member(
            actor=member_only,
            org_id=acme.id,
            email="t@x.com",
            user_id=None,
            role_id=role_member.id,
        )


@pytest.mark.django_db
def test_add_to_org_caller_cannot_see_is_not_found(
    admin_acme, beta, role_member, django_user_model
):
    django_user_model.objects.create_user(email="x@x.com", password="StrongPass123!")
    with pytest.raises(OrganizationNotFoundError):
        svc.add_member(
            actor=admin_acme,
            org_id=beta.id,
            email="x@x.com",
            user_id=None,
            role_id=role_member.id,
        )


# ---- change role ----


@pytest.mark.django_db
def test_change_role_updates(
    admin_acme, acme, role_member, role_viewer, django_user_model
):
    bob = django_user_model.objects.create_user(
        email="bob@x.com", password="StrongPass123!"
    )
    m = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)
    out = svc.change_role(actor=admin_acme, membership_id=m.id, role_id=role_viewer.id)
    assert out.role_id == role_viewer.id


@pytest.mark.django_db
def test_change_role_self_is_blocked(admin_acme, acme, role_member):
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    with pytest.raises(SelfMembershipModificationError):
        svc.change_role(actor=admin_acme, membership_id=own.id, role_id=role_member.id)


@pytest.mark.django_db
def test_change_role_cross_org_is_not_found(
    admin_acme, beta, role_member, django_user_model
):
    other = OrganizationUser.objects.create(
        user=django_user_model.objects.create_user(
            email="c@x.com", password="StrongPass123!"
        ),
        org=beta,
        role=role_member,
    )
    with pytest.raises(MembershipNotFoundError):
        svc.change_role(
            actor=admin_acme, membership_id=other.id, role_id=role_member.id
        )


@pytest.mark.django_db
def test_change_role_missing_is_not_found(admin_acme):
    with pytest.raises(MembershipNotFoundError):
        svc.change_role(actor=admin_acme, membership_id=999999, role_id=1)


# ---- remove ----


@pytest.mark.django_db
def test_remove_member(admin_acme, acme, role_member, django_user_model):
    bob = django_user_model.objects.create_user(
        email="rm@x.com", password="StrongPass123!"
    )
    m = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)
    svc.remove_member(actor=admin_acme, membership_id=m.id)
    assert not OrganizationUser.objects.filter(pk=m.id).exists()


@pytest.mark.django_db
def test_remove_self_is_blocked(admin_acme, acme):
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    with pytest.raises(SelfMembershipModificationError):
        svc.remove_member(actor=admin_acme, membership_id=own.id)


@pytest.mark.django_db
def test_remove_last_admin_is_allowed_no_guard(admin_acme, acme, superadmin):
    # admin_acme is the only Org Admin of acme; a superadmin can remove them
    # (no last-org-admin guard — superadmin is the rescue backstop).
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    svc.remove_member(actor=superadmin, membership_id=own.id)
    assert not OrganizationUser.objects.filter(pk=own.id).exists()
