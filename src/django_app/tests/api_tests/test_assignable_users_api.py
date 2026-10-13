import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/admin/memberships/assignable-users/"


@pytest.mark.django_db
def test_anonymous_401():
    assert APIClient().get(URL).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_denied_without_memberships_create(client_as, member_only):
    assert client_as(member_only).get(URL).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_returns_paginated_envelope(
    client_as, admin_acme, acme, role_member, django_user_model
):
    user = django_user_model.objects.create_user(
        email="cand@x.com", password="StrongPass123!", display_name="Cand"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)

    body = client_as(admin_acme).get(URL).json()

    assert set(body.keys()) == {"count", "next", "previous", "results"}
    row = next(r for r in body["results"] if r["email"] == "cand@x.com")
    assert set(row.keys()) == {
        "id",
        "email",
        "display_name",
        "avatar_url",
        "org_ids",
    }
    assert row["org_ids"] == [acme.id]
    assert row["avatar_url"] is None


@pytest.mark.django_db
def test_superadmins_inactive_accounts_and_other_orgs_members_are_not_offered(
    client_as, admin_acme, acme, beta, role_member, django_user_model
):
    def member_of(org, email, **fields):
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!", **fields)
        OrganizationUser.objects.create(user=user, org=org, role=role_member)

    member_of(acme, "offered@x.com")
    member_of(beta, "beta-only@x.com")
    member_of(acme, "api-sa@x.com", is_superadmin=True)
    member_of(acme, "api-off@x.com", is_active=False)

    emails = {row["email"] for row in client_as(admin_acme).get(URL).json()["results"]}

    assert "offered@x.com" in emails
    assert not emails & {"beta-only@x.com", "api-sa@x.com", "api-off@x.com"}


@pytest.mark.django_db
def test_superadmin_sees_orgless_accounts(client_as, superadmin, django_user_model):
    django_user_model.objects.create_user(
        email="api-orgless@x.com", password="StrongPass123!"
    )
    emails = [r["email"] for r in client_as(superadmin).get(URL).json()["results"]]
    assert "api-orgless@x.com" in emails


@pytest.mark.django_db
def test_search_filters(client_as, admin_acme, acme, role_member, django_user_model):
    user = django_user_model.objects.create_user(
        email="needle@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)

    hit = client_as(admin_acme).get(URL, {"search": "needle"}).json()
    miss = client_as(admin_acme).get(URL, {"search": "haystack"}).json()

    assert [r["email"] for r in hit["results"]] == ["needle@x.com"]
    assert miss["results"] == []


@pytest.mark.django_db
def test_page_size_honoured(
    client_as, admin_acme, acme, role_member, django_user_model
):
    for i in range(3):
        user = django_user_model.objects.create_user(
            email=f"page{i}@x.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=role_member)

    body = client_as(admin_acme).get(URL, {"page_size": 2}).json()
    assert len(body["results"]) == 2
    assert body["next"] is not None
