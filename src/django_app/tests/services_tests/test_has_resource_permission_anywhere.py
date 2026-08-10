from unittest.mock import MagicMock

import pytest

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.permissions import HasResourcePermissionAnywhere


def _view(action):
    view = MagicMock()
    view.rbac_resource_type = ResourceType.ROLES
    view.rbac_action_map = {"list": Permission.READ, "create": Permission.CREATE}
    view.action = action
    return view


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.mark.django_db
def test_superadmin_bypasses(django_user_model):
    su = django_user_model.objects.create_superuser(
        email="su-any@example.com", password="StrongPass123!"
    )
    req = MagicMock(user=su)
    assert HasResourcePermissionAnywhere().has_permission(req, _view("list")) is True


@pytest.mark.django_db
def test_denied_when_no_roles_permission_anywhere(django_user_model, role_member):
    user = django_user_model.objects.create_user(
        email="member-any@example.com", password="StrongPass123!"
    )
    org = Organization.objects.create(name="Acme-any")
    OrganizationUser.objects.create(user=user, org=org, role=role_member)
    req = MagicMock(user=user)
    assert HasResourcePermissionAnywhere().has_permission(req, _view("list")) is False


@pytest.mark.django_db
def test_allowed_when_roles_read_in_one_org(django_user_model, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-any@example.com", password="StrongPass123!"
    )
    org = Organization.objects.create(name="Acme-any-2")
    OrganizationUser.objects.create(user=user, org=org, role=role_org_admin)
    req = MagicMock(user=user)
    assert HasResourcePermissionAnywhere().has_permission(req, _view("list")) is True
    # Org Admin has ROLES CRUD, so create is also allowed "anywhere".
    assert HasResourcePermissionAnywhere().has_permission(req, _view("create")) is True
