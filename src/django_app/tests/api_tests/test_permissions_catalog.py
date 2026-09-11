import pytest

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_catalog_marks_org_create_delete_as_platform(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    orgs = next(r for r in body["resource_types"] if r["code"] == "organizations")
    assert orgs["applicable_actions"] == ["read", "update"]
    assert orgs["platform_actions"] == ["create", "delete"]

    members = next(r for r in body["resource_types"] if r["code"] == "memberships")
    assert members["applicable_actions"] == ["create", "read", "update", "delete"]
    assert members["platform_actions"] == []

    # Every resource entry carries the key (default []).
    assert all("platform_actions" in r for r in body["resource_types"])


@pytest.mark.django_db
def test_catalog_exposes_recommended_with(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    flows = next(r for r in body["resource_types"] if r["code"] == "flows")

    assert flows["recommended_with"]["create"] == [
        {"resource_type": "flows", "action": "read"},
        {"resource_type": "projects", "action": "read"},
        {"resource_type": "llm_configs", "action": "read"},
    ]
    assert flows["recommended_with"]["delete"] == [
        {"resource_type": "flows", "action": "read"}
    ]


@pytest.mark.django_db
def test_recommended_with_covers_every_applicable_action(client_as, admin_acme):
    """Every grantable action is a key, empty list included, so the client can
    index without nil-checks."""
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    for resource in body["resource_types"]:
        assert set(resource["recommended_with"]) == set(resource["applicable_actions"])

    tools = next(r for r in body["resource_types"] if r["code"] == "tools")
    assert tools["recommended_with"]["read"] == []


@pytest.mark.django_db
def test_recommended_with_omits_platform_actions(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    orgs = next(r for r in body["resource_types"] if r["code"] == "organizations")
    assert set(orgs["recommended_with"]) == {"read", "update"}


@pytest.mark.django_db
def test_catalog_exposes_api_keys_as_an_admin_resource(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    api_keys = next(r for r in body["resource_types"] if r["code"] == "api_keys")

    assert api_keys["group"] == "admin"
    assert api_keys["label"] == "API Keys"
    assert api_keys["applicable_actions"] == ["read", "delete"]
    assert api_keys["platform_actions"] == []


@pytest.mark.django_db
def test_catalog_orders_api_keys_after_roles(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    admin_codes = [r["code"] for r in body["resource_types"] if r["group"] == "admin"]

    assert admin_codes == ["organizations", "memberships", "roles", "api_keys"]


@pytest.mark.django_db
def test_catalog_secrets_no_longer_claims_api_keys(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    secrets = next(r for r in body["resource_types"] if r["code"] == "secrets")

    assert secrets["label"] == "Secrets"
    assert "API" not in secrets["description"]
    assert secrets["applicable_actions"] == ["create", "read", "update", "delete"]


@pytest.mark.django_db
def test_catalog_recommends_read_alongside_api_key_delete(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    api_keys = next(r for r in body["resource_types"] if r["code"] == "api_keys")

    assert api_keys["recommended_with"]["delete"] == [
        {"resource_type": "api_keys", "action": "read"}
    ]
    assert api_keys["recommended_with"]["read"] == []
