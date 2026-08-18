"""End-to-end tests for /api/admin/organizations/ (Story 4)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import Organization, OrganizationUser, Role


# ---- fixtures ----


@pytest.fixture
def superadmin_jwt(superadmin_user):
    return str(RefreshToken.for_user(superadmin_user).access_token)


@pytest.fixture
def viewer_role(db):
    return Role.objects.get(name="Viewer", is_built_in=True, org__isnull=True)


@pytest.fixture
def org_factory(db, viewer_role):
    """Creates orgs with optional members. Avoids bare Organization.create()
    in tests so member_count expectations stay explicit.
    """

    counter = {"i": 0}

    def _create(name: str, *, is_active: bool = True, member_count: int = 0):
        org = Organization.objects.create(name=name, is_active=is_active)
        for _ in range(member_count):
            counter["i"] += 1
            User = get_user_model()
            u = User.objects.create_user(
                email=f"member{counter['i']}@example.com", password="UserPass123!"
            )
            OrganizationUser.objects.create(user=u, org=org, role=viewer_role)
        return org

    return _create


def _auth(client, jwt):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt}")
    return client


# ---- LIST ----


@pytest.mark.django_db
def test_list_returns_all_orgs_active_first_then_alpha(
    api_client, superadmin_jwt, org_factory
):
    org_factory("ZetaInactive", is_active=False)
    org_factory("Beta", is_active=True)
    org_factory("Alpha", is_active=True)

    response = _auth(api_client, superadmin_jwt).get("/api/admin/organizations/")
    assert response.status_code == 200
    names = [o["name"] for o in response.json()["results"]]
    # Active first, alphabetical within each section.
    assert "Alpha" in names and "Beta" in names and "ZetaInactive" in names
    assert names.index("Alpha") < names.index("Beta")
    assert names.index("Beta") < names.index("ZetaInactive")


@pytest.mark.django_db
def test_list_filter_is_active_true(api_client, superadmin_jwt, org_factory):
    org_factory("Active1", is_active=True)
    org_factory("Inactive1", is_active=False)

    response = _auth(api_client, superadmin_jwt).get(
        "/api/admin/organizations/?is_active=true"
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(o["is_active"] is True for o in results)
    assert "Inactive1" not in [o["name"] for o in results]


@pytest.mark.django_db
def test_list_filter_is_active_false(api_client, superadmin_jwt, org_factory):
    org_factory("Active1", is_active=True)
    org_factory("Inactive1", is_active=False)

    response = _auth(api_client, superadmin_jwt).get(
        "/api/admin/organizations/?is_active=false"
    )
    assert response.status_code == 200
    names = [o["name"] for o in response.json()["results"]]
    assert "Inactive1" in names
    assert "Active1" not in names


@pytest.mark.django_db
def test_list_member_count_matches_actual_rows(api_client, superadmin_jwt, org_factory):
    org_factory("Empty", member_count=0)
    org_factory("Three", member_count=3)

    response = _auth(api_client, superadmin_jwt).get("/api/admin/organizations/")
    body = {o["name"]: o for o in response.json()["results"]}
    assert body["Empty"]["member_count"] == 0
    assert body["Three"]["member_count"] == 3


@pytest.mark.django_db
def test_list_non_superadmin_sees_only_own_orgs(api_client, jwt_tokens, org_factory):
    # regular_user is Org Admin of the default org (ORGANIZATIONS.READ there),
    # but not a member of Foo — the permission-aware list returns only their org.
    org_factory("Foo")
    response = _auth(api_client, jwt_tokens["access"]).get("/api/admin/organizations/")
    assert response.status_code == 200
    names = [o["name"] for o in response.json()["results"]]
    assert "Foo" not in names
    assert "Default Organization" in names


@pytest.mark.django_db
def test_list_rejects_anonymous(api_client, org_factory):
    org_factory("Foo")
    response = api_client.get("/api/admin/organizations/")
    assert response.status_code == 401


# ---- CREATE ----


@pytest.mark.django_db
def test_create_happy_path(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": "Acme Inc"}, format="json"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Inc"
    assert body["is_active"] is True
    assert body["member_count"] == 0
    assert "id" in body
    assert Organization.objects.filter(name="Acme Inc").exists()


@pytest.mark.django_db
def test_create_duplicate_exact_name_returns_400(
    api_client, superadmin_jwt, org_factory
):
    org_factory("Acme")
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": "Acme"}, format="json"
    )
    assert response.status_code == 400
    assert response.json().get("code") == "organization_name_conflict"


@pytest.mark.django_db
def test_create_duplicate_case_insensitive_returns_400(
    api_client, superadmin_jwt, org_factory
):
    org_factory("Acme")
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": "ACME"}, format="json"
    )
    assert response.status_code == 400
    assert response.json().get("code") == "organization_name_conflict"


@pytest.mark.django_db
def test_create_empty_name_returns_400(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": ""}, format="json"
    )
    assert response.status_code == 400
    body = response.json()
    assert body.get("code") == "invalid"
    assert "errors" in body


@pytest.mark.django_db
def test_create_whitespace_only_name_returns_400(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": "   "}, format="json"
    )
    assert response.status_code == 400
    assert response.json().get("code") == "invalid"


@pytest.mark.django_db
def test_create_trims_surrounding_whitespace(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/", {"name": "  Acme  "}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Acme"


@pytest.mark.django_db
def test_create_rejects_non_superadmin(api_client, jwt_tokens):
    response = _auth(api_client, jwt_tokens["access"]).post(
        "/api/admin/organizations/", {"name": "Foo"}, format="json"
    )
    assert response.status_code == 403


# ---- PATCH (rename) ----


@pytest.mark.django_db
def test_rename_happy_path(api_client, superadmin_jwt, org_factory):
    org = org_factory("OldName")
    response = _auth(api_client, superadmin_jwt).patch(
        f"/api/admin/organizations/{org.id}/",
        {"name": "NewName"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["name"] == "NewName"
    org.refresh_from_db()
    assert org.name == "NewName"


@pytest.mark.django_db
def test_rename_to_same_name_is_noop(api_client, superadmin_jwt, org_factory):
    org = org_factory("Same")
    response = _auth(api_client, superadmin_jwt).patch(
        f"/api/admin/organizations/{org.id}/",
        {"name": "Same"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Same"


@pytest.mark.django_db
def test_rename_conflict_case_insensitive(api_client, superadmin_jwt, org_factory):
    org_factory("Acme")
    other = org_factory("Other")
    response = _auth(api_client, superadmin_jwt).patch(
        f"/api/admin/organizations/{other.id}/",
        {"name": "ACME"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json().get("code") == "organization_name_conflict"


@pytest.mark.django_db
def test_rename_empty_name(api_client, superadmin_jwt, org_factory):
    org = org_factory("Foo")
    response = _auth(api_client, superadmin_jwt).patch(
        f"/api/admin/organizations/{org.id}/",
        {"name": ""},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_rename_unknown_id_returns_404(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).patch(
        "/api/admin/organizations/999999/",
        {"name": "Foo"},
        format="json",
    )
    assert response.status_code == 404


# ---- DEACTIVATE ----


@pytest.mark.django_db
def test_deactivate_happy_path(api_client, superadmin_jwt, org_factory):
    # Need at least 2 active orgs to bypass the last-active guard.
    org_factory("Keeper")
    org = org_factory("ToDeactivate")

    response = _auth(api_client, superadmin_jwt).post(
        f"/api/admin/organizations/{org.id}/deactivate/"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    org.refresh_from_db()
    assert org.is_active is False


@pytest.mark.django_db
def test_deactivate_already_inactive_is_idempotent(
    api_client, superadmin_jwt, org_factory
):
    org_factory("Keeper")
    org = org_factory("AlreadyOff", is_active=False)

    response = _auth(api_client, superadmin_jwt).post(
        f"/api/admin/organizations/{org.id}/deactivate/"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.django_db
def test_deactivate_last_active_returns_400(api_client, superadmin_jwt, org_factory):
    # Make sure only one active org exists. Other tests / fixtures may have
    # created orgs (e.g. a default org from prior test setup); deactivate all
    # but the one we want to test against.
    Organization.objects.filter(is_active=True).update(is_active=False)
    only_active = org_factory("OnlyOneActive")

    response = _auth(api_client, superadmin_jwt).post(
        f"/api/admin/organizations/{only_active.id}/deactivate/"
    )
    assert response.status_code == 400
    assert response.json().get("code") == "last_active_organization"
    only_active.refresh_from_db()
    assert only_active.is_active is True  # unchanged


@pytest.mark.django_db
def test_deactivate_unknown_id_returns_404(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/999999/deactivate/"
    )
    assert response.status_code == 404


# ---- REACTIVATE ----


@pytest.mark.django_db
def test_reactivate_happy_path(api_client, superadmin_jwt, org_factory):
    org = org_factory("Off", is_active=False)
    response = _auth(api_client, superadmin_jwt).post(
        f"/api/admin/organizations/{org.id}/reactivate/"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True
    org.refresh_from_db()
    assert org.is_active is True


@pytest.mark.django_db
def test_reactivate_already_active_is_idempotent(
    api_client, superadmin_jwt, org_factory
):
    org = org_factory("On", is_active=True)
    response = _auth(api_client, superadmin_jwt).post(
        f"/api/admin/organizations/{org.id}/reactivate/"
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


@pytest.mark.django_db
def test_reactivate_unknown_id_returns_404(api_client, superadmin_jwt):
    response = _auth(api_client, superadmin_jwt).post(
        "/api/admin/organizations/999999/reactivate/"
    )
    assert response.status_code == 404
