import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from plugins.access.declared_access import NON_DECLARABLE_RESOURCE_TYPES
from rbac.models.enums import Permission, ResourceType

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


@pytest.mark.django_db
def test_token_carries_user_audit_claim_for_org_admin(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("audit_token"))

    assert response.status_code == 200, response.data
    assert _decode(response.data["token"])["USER_AUDIT"] == ["read", "export"]


@pytest.mark.django_db
def test_token_with_only_user_audit_permission_is_issued(client_as, custom_role_user, acme):
    user = custom_role_user(acme, "user-audit-only@example.com", {ResourceType.USER_AUDIT: Permission.READ})
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("audit_token"))

    assert response.status_code == 200, response.data
    claims = _decode(response.data["token"])
    assert claims["AUDIT"] == []
    assert claims["USER_AUDIT"] == ["read"]


@pytest.mark.django_db
def test_token_refused_without_either_permission(client_as, member_only, acme):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("audit_token"))

    assert response.status_code == 403


def test_plugin_manifest_cannot_declare_user_audit():
    assert ResourceType.USER_AUDIT.value in NON_DECLARABLE_RESOURCE_TYPES
