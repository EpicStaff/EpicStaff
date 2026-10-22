"""/api/permissions/catalog/: the permission matrix the role editor renders."""

import pytest

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def catalog(client_as, admin_acme):
    return client_as(admin_acme).get("/api/permissions/catalog/").json()


def _resource(catalog, code):
    return next(resource for resource in catalog["resource_types"] if resource["code"] == code)


@pytest.mark.django_db
def test_catalog_invariants_the_role_editor_relies_on(catalog):
    # Matrix column order: View leads, then the actions built on it.
    assert [action["code"] for action in catalog["actions"]] == ["read", "create", "update", "delete", "export", "use"]
    assert [r["code"] for r in catalog["resource_types"] if r["group"] == "admin"] == [
        "organizations", "memberships", "roles", "api_keys", "audit",
    ]
    for resource in catalog["resource_types"]:
        # Every grantable action is a key (empty list included) so the client indexes without
        # nil-checks; platform-only actions are never recommended.
        assert set(resource["recommended_with"]) == set(resource["applicable_actions"])
        assert not set(resource["platform_actions"]) & set(resource["recommended_with"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # Org create/delete are superadmin-only; only read/update are grantable.
        ("organizations", {"group": "admin", "applicable_actions": ["read", "update"], "platform_actions": ["create", "delete"]}),
        ("memberships", {"applicable_actions": ["create", "read", "update", "delete"], "platform_actions": []}),
        ("api_keys", {
            "group": "admin", "label": "API Keys", "applicable_actions": ["read", "delete"], "platform_actions": [],
            "recommended_with": {"delete": [{"resource_type": "api_keys", "action": "read"}], "read": []},
        }),
        ("secrets", {"label": "Secrets", "applicable_actions": ["create", "read", "delete", "use"]}),
    ],
)
def test_catalog_entries(catalog, code, expected):
    resource = _resource(catalog, code)

    assert {key: resource[key] for key in expected} == expected
    if code == "secrets":
        assert "API" not in resource["description"]


@pytest.mark.django_db
def test_catalog_exposes_use_on_secrets_and_flows_only(catalog):
    use = next(action for action in catalog["actions"] if action["code"] == "use")

    assert use == {"code": "use", "label": "Use", "bit": 64}
    assert [r["code"] for r in catalog["resource_types"] if "use" in r["applicable_actions"]] == ["flows", "secrets"]
    assert _resource(catalog, "flows")["recommended_with"]["use"] == [{"resource_type": "flows", "action": "read"}]


@pytest.mark.django_db
def test_catalog_recommends_what_a_flow_action_needs(catalog):
    flows = _resource(catalog, "flows")

    assert flows["recommended_with"]["create"] == [
        {"resource_type": "flows", "action": "read"},
        {"resource_type": "projects", "action": "read"},
        {"resource_type": "llm_configs", "action": "read"},
    ]
    assert flows["recommended_with"]["delete"] == [{"resource_type": "flows", "action": "read"}]
    assert _resource(catalog, "tools")["recommended_with"]["read"] == []
