import pytest
from rest_framework import status

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


# ---- retrieve ----


@pytest.mark.django_db
def test_org_admin_retrieves_own_org(client_as, admin_acme, acme):
    resp = client_as(admin_acme).get(detail_url(acme.id))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == acme.id


@pytest.mark.django_db
def test_org_admin_retrieve_cross_org_404(client_as, admin_acme, beta):
    resp = client_as(admin_acme).get(detail_url(beta.id))
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---- rename (ORGANIZATIONS.UPDATE) ----


@pytest.mark.django_db
def test_org_admin_can_rename_own_org(client_as, admin_acme, acme):
    resp = client_as(admin_acme).patch(
        detail_url(acme.id), {"name": "Acme 2"}, format="json"
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["name"] == "Acme 2"


@pytest.mark.django_db
def test_org_admin_rename_cross_org_404(client_as, admin_acme, beta):
    resp = client_as(admin_acme).patch(
        detail_url(beta.id), {"name": "X"}, format="json"
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---- platform actions stay superadmin-only ----


@pytest.mark.django_db
def test_org_admin_cannot_create_org(client_as, admin_acme):
    resp = client_as(admin_acme).post(LIST_URL, {"name": "New Co"}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_org_admin_cannot_deactivate_org(client_as, admin_acme, acme):
    resp = client_as(admin_acme).post(f"/api/admin/organizations/{acme.id}/deactivate/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_superadmin_can_create_org(client_as, superadmin):
    resp = client_as(superadmin).post(LIST_URL, {"name": "SA New Co"}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
