"""What the API refuses: API keys on JWT-only surfaces, missing org context, other orgs, Viewer writes.

Every check asserts the error envelope's `code`, never its message.
"""

import pytest

from helpers.api import BASE_URL, ApiClient, assert_error
from helpers.bootstrap import Bootstrap, unique_suffix


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/profile/api-keys/", {"name": "e2e-from-key", "expires_in_days": 1}),
        ("/api/admin/roles/", {"name": "e2e-from-key", "permissions": []}),
        ("/api/secrets/", {"name": "e2e-from-key", "value": "not-a-real-secret"}),
    ],
    ids=["api-keys", "admin-roles", "secrets"],
)
def test_api_key_cannot_use_jwt_only_endpoints(
    user_client: ApiClient, org_id: int, path: str, body: dict
) -> None:
    payload = {**body, "org_id": org_id} if path == "/api/admin/roles/" else body
    response = user_client.post(path, json=payload, expect=None)
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
