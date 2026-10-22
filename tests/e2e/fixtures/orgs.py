"""Cross-org and low-privilege resources for the negative tests.

superadmin_access_token -> other_org -> other_org_graph -> other_org_session
superadmin_client -> viewer_role_id -> viewer_client
"""

from collections.abc import Iterator

import pytest

from helpers.api import BASE_URL, ApiClient
from helpers.bootstrap import EMAIL_DOMAIN, new_password, unique_suffix
from helpers.flows import create_flow
from helpers.payloads import start_end_flow_save_payload
from helpers.redaction import Secret, protect


@pytest.fixture(scope="session")
def other_org(superadmin_client: ApiClient) -> dict:
    """A second organization the test user is not a member of."""
    return superadmin_client.post(
        "/api/admin/organizations/", json={"name": f"e2e-other-{unique_suffix()}"}, expect=201
    ).json()


@pytest.fixture(scope="session")
def other_org_superadmin_client(
    superadmin_access_token: Secret, other_org: dict
) -> Iterator[ApiClient]:
    """Superadmin acting inside the second organization (superadmin needs no membership)."""
    client = ApiClient.with_jwt(BASE_URL, superadmin_access_token, other_org["id"])
    yield client
    client.close()


@pytest.fixture(scope="session")
def other_org_graph(other_org_superadmin_client: ApiClient) -> dict:
    """A Start -> End graph in the second organization (an empty graph cannot be run)."""
    return create_flow(
        other_org_superadmin_client,
        f"e2e-other-org-graph-{unique_suffix()}",
        start_end_flow_save_payload,
    ).saved


@pytest.fixture(scope="session")
def other_org_session_id(other_org_superadmin_client: ApiClient, other_org_graph: dict) -> int:
    """A session owned by the second organization; only the row matters, not the run."""
    return other_org_superadmin_client.post(
        "/api/run-session/", json={"graph_id": other_org_graph["id"], "variables": {}}, expect=201
    ).json()["session_id"]


@pytest.fixture(scope="session")
def viewer_role_id(superadmin_client: ApiClient) -> int:
    body = superadmin_client.get("/api/admin/roles/").json()
    [viewer] = [role for role in body["built_in_roles"] if role["name"] == "Viewer"]
    return viewer["id"]


@pytest.fixture(scope="session")
def viewer_client(
    superadmin_client: ApiClient, anonymous_client: ApiClient, viewer_role_id: int, org_id: int
) -> Iterator[ApiClient]:
    """A second user with the built-in Viewer role, authenticated with their own API key.

    Logs in exactly once: login is throttled per IP + email.
    """
    email = f"e2e-viewer-{unique_suffix()}@{EMAIL_DOMAIN}"
    password = new_password()
    superadmin_client.post(
        "/api/admin/users/",
        json={"email": email, "password": password, "organization_id": org_id, "role_id": viewer_role_id},
        expect=201,
    )
    login = protect(
        anonymous_client.post("/api/auth/login/", json={"email": email, "password": password}).json()
    )
    viewer_with_jwt = ApiClient.with_jwt(BASE_URL, login["access"])
    del login
    try:
        key = protect(
            viewer_with_jwt.post(
                "/api/profile/api-keys/", json={"name": "e2e-viewer", "expires_in_days": 1}, expect=201
            ).json()
        )
    finally:
        viewer_with_jwt.close()
    client = ApiClient.with_api_key(BASE_URL, key["api_key"], org_id)
    del key
    yield client
    client.close()
