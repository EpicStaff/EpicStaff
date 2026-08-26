"""
EST-1869 security fix: `TokenIntrospectView` now also returns `org_ids`
(orgs the token's user belongs to) and `is_superadmin`, so the `realtime`
service can verify a connecting user actually owns the org a
`connection_key` was provisioned for (see `src/realtime/api/main.py`'s
`root()` handler, and `RealtimeAgentChatData.org_id` in
`src/shared/models/agents.py`). Before this fix, introspect returned only
`user_id`/`email`/`scopes` — no ownership data to check against.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser

INTROSPECT_URL = "/api/auth/introspect/"


@pytest.mark.django_db
def test_introspect_returns_org_ids_for_regular_user(
    env_api_key, jwt_tokens, default_org
):
    raw, _ = env_api_key
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)

    resp = client.post(
        INTROSPECT_URL, data={"token": jwt_tokens["access"]}, format="json"
    )

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["org_ids"] == [default_org.pk]
    assert body["is_superadmin"] is False


@pytest.mark.django_db
def test_introspect_returns_all_memberships_for_multi_org_user(
    env_api_key, regular_user, jwt_tokens, default_org, org_admin_role
):
    other_org = Organization.objects.create(name="Other Org")
    OrganizationUser.objects.create(
        user=regular_user, org=other_org, role=org_admin_role
    )

    raw, _ = env_api_key
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)

    resp = client.post(
        INTROSPECT_URL, data={"token": jwt_tokens["access"]}, format="json"
    )

    assert resp.status_code == status.HTTP_200_OK
    assert set(resp.json()["org_ids"]) == {default_org.pk, other_org.pk}


@pytest.mark.django_db
def test_introspect_marks_superadmin(env_api_key, superadmin_jwt_tokens):
    raw, _ = env_api_key
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)

    resp = client.post(
        INTROSPECT_URL,
        data={"token": superadmin_jwt_tokens["access"]},
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["is_superadmin"] is True
    assert body["org_ids"] == []
