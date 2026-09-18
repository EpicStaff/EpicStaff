"""Regression tests for OrgContextService._assert_membership on a
nonexistent X-Organization-Id.

Superadmin bypasses membership but the org must still exist as a real id
(see tables/services/rbac/org_context_service.py docstring). Before the
fix, a superadmin sending a bogus org id hit Organization.objects.get()
unguarded downstream and got an uncaught DoesNotExist -> 500. Now it
raises OrganizationNotFoundError -> clean 404.

Non-superadmins never reach that code path: membership .exists() is
False for a bogus org id regardless of org existence, so they keep
getting 403 (and must NOT start getting 404 -- that would leak whether
the org id exists to a non-member).
"""

import pytest
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole

NONEXISTENT_ORG_ID = 999_999


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_user(
        email="root@example.com", password="StrongPass123!", is_superadmin=True
    )


def _client(user, org_id):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_id))
    return client


@pytest.fixture
def superadmin_client_bad_org(superadmin):
    return _client(superadmin, NONEXISTENT_ORG_ID)


@pytest.fixture
def member_client_bad_org(member_a):
    return _client(member_a, NONEXISTENT_ORG_ID)


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/agent-definitions/", "/api/surfaces/"])
def test_superadmin_list_nonexistent_org_returns_404_not_500(
    superadmin_client_bad_org, url
):
    response = superadmin_client_bad_org.get(url)

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert body["code"] == "organization_not_found"


@pytest.mark.django_db
def test_superadmin_create_agent_definition_nonexistent_org_returns_404_not_500(
    superadmin_client_bad_org,
):
    response = superadmin_client_bad_org.post(
        "/api/agent-definitions/",
        {"name": "ghost-org-agent", "instructions": "do things"},
        format="json",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert body["code"] == "organization_not_found"


@pytest.mark.django_db
def test_superadmin_create_surface_nonexistent_org_returns_404_not_500(
    superadmin_client_bad_org,
):
    response = superadmin_client_bad_org.post(
        "/api/surfaces/",
        {"name": "ghost-org-surface"},
        format="json",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert body["code"] == "organization_not_found"


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/agent-definitions/", "/api/surfaces/"])
def test_non_superadmin_list_nonexistent_org_still_returns_403_not_404(
    member_client_bad_org, url
):
    response = member_client_bad_org.get(url)

    assert response.status_code == 403
    body = response.json()
    assert body["status_code"] == 403
    assert body["code"] == "org_membership_required"
