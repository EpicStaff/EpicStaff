"""Shared fixtures for the cross-org RBAC admin tests (memberships / orgs /
roles). Star-imported by the cross-org test modules — mirrors the codebase's
`from .fixtures import *` pattern in tests/conftest.py.

Uses a distinctly-named `client_as` factory instead of `auth_client` so it does
NOT shadow the fixed `auth_client` fixture defined in tests/conftest.py (which
other suites rely on).
"""

import pytest
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def client_as():
    """Factory → an APIClient force-authenticated as the given user."""

    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def acme(db):
    return Organization.objects.create(name="Acme-xorg")


@pytest.fixture
def beta(db):
    return Organization.objects.create(name="Beta-xorg")


@pytest.fixture
def admin_acme(db, django_user_model, acme, role_org_admin):
    """Org Admin (built-in) of Acme only."""
    user = django_user_model.objects.create_user(
        email="admin-acme-xorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def member_only(db, django_user_model, acme, role_member):
    """Plain Member of Acme (no admin permissions)."""
    user = django_user_model.objects.create_user(
        email="member-only-xorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_user(
        email="superadmin-xorg@example.com",
        password="StrongPass123!",
        is_superadmin=True,
    )
