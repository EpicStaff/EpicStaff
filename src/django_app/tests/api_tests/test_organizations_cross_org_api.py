import pytest
from rest_framework import status

from rbac.models import OrganizationUser

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = "/api/admin/organizations/"


def detail_url(org_id):
    return f"/api/admin/organizations/{org_id}/"


# ---- list (permission-aware) ----


@pytest.mark.django_db
def test_org_admin_sees_only_their_org(client_as, admin_acme, acme, beta):
    body = client_as(admin_acme).get(LIST_URL).json()
    ids = {o["id"] for o in body["results"]}
    assert ids == {acme.id}


@pytest.mark.django_db
def test_member_cannot_open_org_admin_list(client_as, member_only):
    # member_only has organizations=0 → no ORGANIZATIONS.READ anywhere → door gate 403.
    resp = client_as(member_only).get(LIST_URL)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_forbidden_org_ids_403(client_as, admin_acme, beta):
    resp = client_as(admin_acme).get(LIST_URL + f"?org_ids={beta.id}")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_superadmin_sees_all(client_as, superadmin, acme, beta):
    body = client_as(superadmin).get(LIST_URL).json()
    ids = {o["id"] for o in body["results"]}
    assert {acme.id, beta.id}.issubset(ids)


# ---- an Org Admin manages their own org only ----


@pytest.mark.django_db
def test_org_admin_reads_and_renames_their_own_org(client_as, admin_acme, acme):
    client = client_as(admin_acme)

    assert client.get(detail_url(acme.id)).json()["id"] == acme.id
    response = client.patch(detail_url(acme.id), {"name": "Acme 2"}, format="json")

    assert (response.status_code, response.json()["name"]) == (status.HTTP_200_OK, "Acme 2")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("post", "", {"name": "New Co"}), ("post", "{acme}/deactivate/", None)],
    ids=["create", "deactivate"],
)
def test_platform_actions_stay_superadmin_only(client_as, admin_acme, acme, method, path, body):
    response = getattr(client_as(admin_acme), method)(LIST_URL + path.format(acme=acme.id), body, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    acme.refresh_from_db()
    assert acme.is_active is True


# ---- visibility: an org the caller cannot see is 404, never 403 ----


@pytest.fixture
def admin_beta_member_acme(db, django_user_model, acme, beta, role_org_admin, role_member):
    """Org Admin of beta (clears the ORGANIZATIONS door gate) and a plain Member of
    acme (organizations=0 there)."""
    user = django_user_model.objects.create_user(email="admin-beta-member-acme-org@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.parametrize(
    ("caller", "target"),
    [("admin_acme", "beta"), ("admin_beta_member_acme", "acme")],
    ids=["another-orgs-admin", "member-without-org-bits"],
)
def test_an_org_the_caller_cannot_manage_looks_like_it_does_not_exist(request, client_as, caller, target, method):
    org = request.getfixturevalue(target)
    original = org.name

    response = getattr(client_as(request.getfixturevalue(caller)), method)(
        detail_url(org.id), {"name": "Renamed-by-outsider"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "organization_not_found"
    org.refresh_from_db()
    assert org.name == original
