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
def test_member_without_the_bit_is_denied(service, member_only, acme):
    with pytest.raises(PermissionDenied):
        service.authorize_any_org(member_only, {acme.id}, Permission.DELETE)


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
