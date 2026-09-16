import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import OrganizationUser

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
def test_excludes_users_from_unreadable_orgs(
    client_as, admin_acme, beta, role_member, django_user_model
):
    hidden = django_user_model.objects.create_user(
        email="beta-only@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=hidden, org=beta, role=role_member)

    emails = [r["email"] for r in client_as(admin_acme).get(URL).json()["results"]]
    assert "beta-only@x.com" not in emails


@pytest.mark.django_db
def test_excludes_superadmins(
    client_as, admin_acme, acme, role_member, django_user_model
):
    sa = django_user_model.objects.create_user(
        email="api-sa@x.com", password="StrongPass123!", is_superadmin=True
    )
    OrganizationUser.objects.create(user=sa, org=acme, role=role_member)

    emails = [r["email"] for r in client_as(admin_acme).get(URL).json()["results"]]
    assert "api-sa@x.com" not in emails


@pytest.mark.django_db
def test_excludes_inactive(client_as, admin_acme, acme, role_member, django_user_model):
    off = django_user_model.objects.create_user(
        email="api-off@x.com", password="StrongPass123!", is_active=False
    )
    OrganizationUser.objects.create(user=off, org=acme, role=role_member)

    emails = [r["email"] for r in client_as(admin_acme).get(URL).json()["results"]]
    assert "api-off@x.com" not in emails


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
