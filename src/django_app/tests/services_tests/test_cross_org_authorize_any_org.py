import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import RoleNotFoundError

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class _Service(CrossOrgResourceService):
    rbac_resource_type = ResourceType.ROLES
    not_found_exception = RoleNotFoundError


@pytest.fixture
def service():
    return _Service()


@pytest.mark.django_db
def test_superadmin_is_authorized_for_any_org(service, superadmin, acme):
    service.authorize_any_org(superadmin, {acme.id}, Permission.DELETE)


@pytest.mark.django_db
def test_no_shared_org_raises_the_resource_not_found(service, admin_acme, beta):
    with pytest.raises(RoleNotFoundError):
        service.authorize_any_org(admin_acme, {beta.id}, Permission.DELETE)


@pytest.mark.django_db
def test_empty_org_set_raises_the_resource_not_found(service, admin_acme):
    with pytest.raises(RoleNotFoundError):
        service.authorize_any_org(admin_acme, set(), Permission.DELETE)


@pytest.mark.django_db
def test_bit_in_any_one_org_authorizes(
    service, django_user_model, role_org_admin, role_member, acme, beta
):
    user = django_user_model.objects.create_user(
        email="mixed-scope@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)

    service.authorize_any_org(user, {acme.id, beta.id}, Permission.DELETE)


@pytest.mark.django_db
def test_inactive_org_does_not_count_as_reachable(
    service, django_user_model, role_org_admin
):
    dormant = Organization.objects.create(name="Dormant-xorg", is_active=False)
    user = django_user_model.objects.create_user(
        email="dormant-admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=dormant, role=role_org_admin)

    with pytest.raises(RoleNotFoundError):
        service.authorize_any_org(user, {dormant.id}, Permission.DELETE)


@pytest.mark.django_db
def test_verb_without_read_is_still_authorized(service, django_user_model, acme):
    """Reachability keys on membership, not READ, so a role granting the verb
    without READ is never told the row does not exist."""
    deleter_role = Role.objects.create(
        name="DeleterOnly-xorg", org=acme, is_built_in=False
    )
    RolePermission.objects.create(
        role=deleter_role, resource_type="roles", permissions=int(Permission.DELETE)
    )
    user = django_user_model.objects.create_user(
        email="delete-no-read@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=deleter_role)

    assert service.resolve_readable_org_ids(user) == set()
    service.authorize_any_org(user, {acme.id}, Permission.DELETE)


# ---- visibility rule (existential form) ----
#
# `authorize_any_org` is `resolve_for_write` over a set of orgs, so it applies
# the same split: the row is visible when SOME reachable org grants READ or the
# action, and only then can a missing verb surface as 403.


@pytest.mark.django_db
def test_reachable_without_read_or_verb_is_not_found(service, django_user_model, acme):
    """A plain member of the owner's org holds no api_keys/roles bits at all,
    so the row is not visible to them — 403 would confirm the id."""
    bystander_role = Role.objects.create(
        name="NoRolesBits-xorg", org=acme, is_built_in=False
    )
    user = django_user_model.objects.create_user(
        email="no-bits-anyorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=bystander_role)

    with pytest.raises(RoleNotFoundError):
        service.authorize_any_org(user, {acme.id}, Permission.DELETE)


@pytest.mark.django_db
def test_read_without_verb_is_denied(service, django_user_model, acme):
    """READ makes the row visible, so the missing DELETE is an honest 403."""
    reader_role = Role.objects.create(
        name="ReaderOnly-anyorg", org=acme, is_built_in=False
    )
    RolePermission.objects.create(
        role=reader_role, resource_type="roles", permissions=int(Permission.READ)
    )
    user = django_user_model.objects.create_user(
        email="read-no-delete-anyorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=reader_role)

    with pytest.raises(PermissionDenied):
        service.authorize_any_org(user, {acme.id}, Permission.DELETE)
