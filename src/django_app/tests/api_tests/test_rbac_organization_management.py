"""End-to-end tests for /api/admin/organizations/ (Story 4)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import Organization, OrganizationUser, Role


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


URL = "/api/admin/organizations/"


# ---- LIST ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "expected"),
    [("", ["Alpha", "Beta", "ZetaInactive"]), ("?is_active=true", ["Alpha", "Beta"]), ("?is_active=false", ["ZetaInactive"])],
    ids=["all-active-first-then-alphabetical", "active", "inactive"],
)
def test_list_filters_and_orders_orgs(api_client, superadmin_jwt, org_factory, query, expected):
    org_factory("ZetaInactive", is_active=False)
    org_factory("Beta")
    org_factory("Alpha")

    response = _auth(api_client, superadmin_jwt).get(URL + query)

    assert response.status_code == 200
    names = [org["name"] for org in response.json()["results"] if org["name"] in {"Alpha", "Beta", "ZetaInactive"}]
    assert names == expected


@pytest.mark.django_db
def test_list_member_count_matches_actual_rows(api_client, superadmin_jwt, org_factory):
    org_factory("Empty", member_count=0)
    org_factory("Three", member_count=3)

    response = _auth(api_client, superadmin_jwt).get(URL)

    body = {org["name"]: org for org in response.json()["results"]}
    assert (body["Empty"]["member_count"], body["Three"]["member_count"]) == (0, 3)


@pytest.mark.django_db
def test_list_non_superadmin_sees_only_own_orgs(api_client, jwt_tokens, org_factory):
    # regular_user is Org Admin of the default org (ORGANIZATIONS.READ there) only.
    org_factory("Foo")

    response = _auth(api_client, jwt_tokens["access"]).get(URL)

    assert response.status_code == 200
    names = [org["name"] for org in response.json()["results"]]
    assert "Foo" not in names
    assert "Default Organization" in names


@pytest.mark.django_db
def test_list_rejects_anonymous(api_client):
    assert api_client.get(URL).status_code == 401


# ---- CREATE / RENAME ----


@pytest.mark.django_db
@pytest.mark.parametrize(("name", "saved"), [("Acme Inc", "Acme Inc"), ("  Acme  ", "Acme")], ids=["plain", "trimmed"])
def test_create(api_client, superadmin_jwt, name, saved):
    response = _auth(api_client, superadmin_jwt).post(URL, {"name": name}, format="json")

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["is_active"], body["member_count"]) == (saved, True, 0)
    assert Organization.objects.filter(pk=body["id"], name=saved).exists()


@pytest.mark.django_db
def test_create_rejects_non_superadmin(api_client, jwt_tokens):
    response = _auth(api_client, jwt_tokens["access"]).post(URL, {"name": "Foo"}, format="json")

    assert response.status_code == 403
    assert not Organization.objects.filter(name="Foo").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("new_name", ["NewName", "OldName"], ids=["rename", "same-name-noop"])
def test_rename(api_client, superadmin_jwt, org_factory, new_name):
    org = org_factory("OldName")

    response = _auth(api_client, superadmin_jwt).patch(f"{URL}{org.id}/", {"name": new_name}, format="json")

    assert response.status_code == 200
    assert response.json()["name"] == new_name
    org.refresh_from_db()
    assert org.name == new_name


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["create", "rename"])
@pytest.mark.parametrize(
    ("name", "code"),
    [("Acme", "organization_name_conflict"), ("ACME", "organization_name_conflict"), ("", "invalid"), ("   ", "invalid")],
    ids=["taken", "taken-other-case", "empty", "whitespace"],
)
def test_org_names_must_be_present_and_unique_ignoring_case(
    api_client, superadmin_jwt, org_factory, operation, name, code
):
    org_factory("Acme")
    other = org_factory("Other")
    client = _auth(api_client, superadmin_jwt)

    if operation == "create":
        response = client.post(URL, {"name": name}, format="json")
    else:
        response = client.patch(f"{URL}{other.id}/", {"name": name}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == code
    assert Organization.objects.filter(name__iexact="acme").count() == 1
    other.refresh_from_db()
    assert other.name == "Other"


# ---- DEACTIVATE / REACTIVATE ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "starts_active", "ends_active"),
    [("deactivate", True, False), ("deactivate", False, False), ("reactivate", False, True), ("reactivate", True, True)],
    ids=["deactivate", "deactivate-idempotent", "reactivate", "reactivate-idempotent"],
)
def test_activation_changes(api_client, superadmin_jwt, org_factory, action, starts_active, ends_active):
    # A second active org keeps the last-active guard out of the way.
    org_factory("Keeper")
    org = org_factory("Target", is_active=starts_active)

    response = _auth(api_client, superadmin_jwt).post(f"{URL}{org.id}/{action}/")

    assert response.status_code == 200
    assert response.json()["is_active"] is ends_active
    org.refresh_from_db()
    assert org.is_active is ends_active


@pytest.mark.django_db
def test_the_last_active_org_cannot_be_deactivated(api_client, superadmin_jwt, org_factory):
    Organization.objects.filter(is_active=True).update(is_active=False)
    only_active = org_factory("OnlyOneActive")

    response = _auth(api_client, superadmin_jwt).post(f"{URL}{only_active.id}/deactivate/")

    assert response.status_code == 400
    assert response.json()["code"] == "last_active_organization"
    only_active.refresh_from_db()
    assert only_active.is_active is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "suffix"),
    [("patch", ""), ("post", "deactivate/"), ("post", "reactivate/")],
    ids=["rename", "deactivate", "reactivate"],
)
def test_unknown_org_is_404(api_client, superadmin_jwt, method, suffix):
    response = getattr(_auth(api_client, superadmin_jwt), method)(f"{URL}999999/{suffix}", {"name": "Foo"}, format="json")

    assert response.status_code == 404
