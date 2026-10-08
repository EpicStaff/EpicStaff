"""What the API refuses: API keys on JWT-only surfaces, missing org context, other orgs, Viewer writes.

Every check asserts the error envelope's `code`, never its message.
"""

import uuid

import pytest

from helpers.api import BASE_URL, ApiClient, assert_error, describe_response, page_results
from helpers.bootstrap import Bootstrap, unique_suffix
from helpers.redaction import protect, register_secret

# An id no row will reach in a fresh test database.
NON_EXISTENT_ID = 2_000_000_000


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/profile/api-keys/", {"name": "e2e-from-key", "expires_in_days": 1}),
        ("/api/secrets/", {"name": "e2e-from-key", "value": "not-a-real-secret"}),
    ],
    ids=["api-keys", "secrets"],
)
def test_api_key_cannot_use_jwt_only_endpoints(
    user_client: ApiClient, path: str, body: dict
) -> None:
    response = user_client.post(path, json=body, expect=None)
    assert_error(response, 403, "permission_denied")


def test_superadmin_api_key_cannot_write_admin_roles(
    superadmin_client: ApiClient, org_id: int
) -> None:
    """Even the superadmin's own key is refused: the gate is the key, not the role."""
    key = protect(
        superadmin_client.post(
            "/api/profile/api-keys/", json={"name": "e2e-superadmin-key", "expires_in_days": 1}, expect=201
        ).json()
    )
    superadmin_with_key = ApiClient.with_api_key(BASE_URL, key["api_key"], org_id)
    del key
    try:
        response = superadmin_with_key.post(
            "/api/admin/roles/",
            json={"org_id": org_id, "name": f"e2e-from-key-{unique_suffix()}", "permissions": []},
            expect=None,
        )
    finally:
        superadmin_with_key.close()
    assert_error(response, 403, "permission_denied")


def test_org_header_is_required(bootstrap: Bootstrap) -> None:
    without_org = ApiClient.with_api_key(BASE_URL, bootstrap.user_api_key, None)
    try:
        response = without_org.get("/api/graphs/", expect=None)
    finally:
        without_org.close()
    assert_error(response, 400, "org_context_required")


def test_graph_of_another_org_is_not_found_from_own_org(
    user_client: ApiClient, other_org_graph: dict
) -> None:
    response = user_client.get(f"/api/graphs/{other_org_graph['id']}/", expect=None)
    assert_error(response, 404, "not_found")


def test_other_org_header_requires_membership(bootstrap: Bootstrap, other_org: dict) -> None:
    in_other_org = ApiClient.with_api_key(BASE_URL, bootstrap.user_api_key, other_org["id"])
    try:
        response = in_other_org.get("/api/graphs/", expect=None)
    finally:
        in_other_org.close()
    assert_error(response, 403, "org_membership_required")


def test_run_session_for_another_orgs_graph_is_not_found(
    user_client: ApiClient, other_org_graph: dict
) -> None:
    response = user_client.post(
        "/api/run-session/", json={"graph_id": other_org_graph["id"], "variables": {}}, expect=None
    )
    assert_error(response, 404, "graph_not_found")


def test_viewer_can_list_but_not_create_graphs(viewer_client: ApiClient) -> None:
    viewer_client.get("/api/graphs/")
    response = viewer_client.post(
        "/api/graphs/", json={"name": f"e2e-viewer-graph-{unique_suffix()}"}, expect=None
    )
    assert_error(response, 403, "permission_denied")


def test_llm_config_cannot_bind_another_orgs_secret(
    user_client: ApiClient,
    other_org_superadmin_client: ApiClient,
    mock_llm_model: dict,
) -> None:
    other_secret = other_org_superadmin_client.post(
        "/api/secrets/",
        json={
            "name": f"e2e-other-org-secret-{unique_suffix()}",
            "value": register_secret(f"other-org-{uuid.uuid4()}"),
        },
        expect=201,
    ).json()
    custom_name = f"e2e-cross-org-llm-{unique_suffix()}"

    def post_config(secret_id: int):
        return user_client.post(
            "/api/llm-configs/",
            json={
                "custom_name": custom_name,
                "model": mock_llm_model["id"],
                "api_key_secret_id": secret_id,
            },
            expect=None,
        )

    # Another org's secret must be indistinguishable from one that does not exist.
    cross_org = post_config(other_secret["id"])
    missing = post_config(NON_EXISTENT_ID)
    observed = (
        f"other org's secret -> {cross_org.status_code} {cross_org.json().get('code')!r}; "
        f"non-existent secret -> {missing.status_code} {missing.json().get('code')!r}"
    )
    assert 400 <= cross_org.status_code < 500, f"{observed}\n{describe_response(cross_org)}"
    assert cross_org.status_code == missing.status_code, observed
    assert cross_org.json().get("code") == missing.json().get("code"), observed

    own_configs = page_results(user_client.get("/api/llm-configs/", params={"limit": 1000}).json())
    assert custom_name not in {config["custom_name"] for config in own_configs}, observed


def test_session_of_another_org_is_not_found(user_client: ApiClient, other_org_session_id: int) -> None:
    response = user_client.get(f"/api/sessions/{other_org_session_id}/", expect=None)
    assert_error(response, 404, "not_found")


def test_graph_list_hides_another_orgs_graph(user_client: ApiClient, other_org_graph: dict) -> None:
    graphs = page_results(user_client.get("/api/graphs/", params={"limit": 1000}).json())
    assert other_org_graph["id"] not in {graph["id"] for graph in graphs}
