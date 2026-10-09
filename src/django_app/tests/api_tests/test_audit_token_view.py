import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from tables.views.audit_token_views import AUDIT_TOKEN_ISSUER
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.AUDIT_JWT_SECRET, algorithms=["HS256"])


@pytest.mark.django_db
def test_audit_token_carries_issuer_and_active_org(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("audit_token"))

    assert response.status_code == 200, response.data
    claims = _decode(response.data["token"])
    assert claims["iss"] == AUDIT_TOKEN_ISSUER
    assert claims["org_id"] == acme.id
    assert claims["user_id"] == admin_acme.id
    assert "aud" not in claims
    assert claims["AUDIT"] == ["read", "export"]
    assert "actions" not in claims


@pytest.mark.django_db
def test_audit_token_is_not_minted_for_an_org_the_caller_does_not_belong_to(
    client_as, admin_acme, beta
):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = client.post(reverse("audit_token"))

    assert response.status_code == 403
    assert "token" not in response.data
