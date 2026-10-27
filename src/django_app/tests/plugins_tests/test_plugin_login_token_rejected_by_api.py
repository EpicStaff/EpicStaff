"""A plugin login token is no credential for EpicStaff's own API."""

import pytest
from plugins.identity.plugin_login_tokens import issue_plugin_login_token
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled")]


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/graphs/"), ("post", "/api/run-session/"), ("get", "/api/profile/")],
)
def test_a_plugin_login_token_does_not_authenticate_epicstaff_s_api(member_only, acme, method, path):
    token = issue_plugin_login_token(user=member_only, org_id=acme.pk, grant_id=1, identifier="weather").token
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_ORGANIZATION_ID=str(acme.pk))

    response = getattr(client, method)(path, {}, format="json")

    assert response.status_code == 401


def test_the_person_s_own_epicstaff_token_does_authenticate(member_only):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(member_only).access_token}")

    assert client.get("/api/profile/").status_code == 200
