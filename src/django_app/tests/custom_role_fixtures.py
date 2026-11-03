"""Fixtures for callers whose custom role holds exactly the permissions a test names.

Star-imported next to `tests.rbac_cross_org_fixtures`, whose `client_as` they build
on; the API key factory uses `issue_api_key` from tests/conftest.py.
"""

import pytest
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission


@pytest.fixture
def custom_role_member(db, django_user_model):
    """Factory → a user of `org` whose custom role holds `grants`.

    `grants` maps a resource type to its permission bits; `name` names the role
    and the user's email, so it must be unique within a test.
    """

    def _make(org, grants, name):
        role = Role.objects.create(name=name, org=org, is_built_in=False)
        for resource_type, permissions in grants.items():
            RolePermission.objects.create(
                role=role, resource_type=resource_type, permissions=int(permissions)
            )
        user = django_user_model.objects.create_user(
            email=f"{name}@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=org, role=role)
        return user

    return _make


@pytest.fixture
def org_client_as(client_as):
    """Factory → `client_as(user)` acting in `org` (X-Organization-Id set)."""

    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


@pytest.fixture
def api_key_client_as(issue_api_key):
    """Factory → an APIClient authenticated by a user API key of `user`, bound to `org`."""

    def _make(user, org):
        raw_key, _ = issue_api_key(user=user, org=org)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


@pytest.fixture
def custom_role_client(custom_role_member, org_client_as, api_key_client_as):
    """Factory → a client of a fresh `custom_role_member`, acting in `org`.

    `via_api_key=True` authenticates with a user API key of that member instead
    of a session: such a key acts with its owner's role.
    """

    def _make(org, grants, name, *, via_api_key=False):
        user = custom_role_member(org, grants, name)
        make_client = api_key_client_as if via_api_key else org_client_as
        return make_client(user, org)

    return _make
