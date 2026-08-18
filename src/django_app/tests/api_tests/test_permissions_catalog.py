import pytest

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_catalog_marks_org_create_delete_as_platform(client_as, admin_acme):
    body = client_as(admin_acme).get("/api/permissions/catalog/").json()
    orgs = next(r for r in body["resource_types"] if r["code"] == "organizations")
    assert orgs["applicable_actions"] == ["read", "update"]
    assert orgs["platform_actions"] == ["create", "delete"]

    users = next(r for r in body["resource_types"] if r["code"] == "users")
    assert users["applicable_actions"] == ["create", "read", "update", "delete"]
    assert users["platform_actions"] == []

    # Every resource entry carries the key (default []).
    assert all("platform_actions" in r for r in body["resource_types"])
