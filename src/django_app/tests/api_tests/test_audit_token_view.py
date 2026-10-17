import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from rbac.models import OrganizationUser, Role, RolePermission
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


def _audit_reader(django_user_model, org, audit_history_days):
    role = Role.objects.create(
        name=f"Auditor {audit_history_days}d",
        org=org,
        is_built_in=False,
        audit_history_days=audit_history_days,
    )
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.AUDIT, permissions=int(Permission.READ)
    )
    user = django_user_model.objects.create_user(
        email=f"auditor-{audit_history_days}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _retention_days(client, org) -> int:
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    response = client.post(reverse("audit_token"))
    assert response.status_code == 200, response.data
    return _decode(response.data["token"])["retention_days"]


@pytest.mark.django_db
@pytest.mark.parametrize("audit_history_days", [0, 30])
def test_retention_days_comes_from_the_callers_role(
    client_as, django_user_model, acme, audit_history_days
):
    user = _audit_reader(django_user_model, acme, audit_history_days)

    assert _retention_days(client_as(user), acme) == audit_history_days


@pytest.mark.django_db
def test_org_admin_retention_is_unlimited(client_as, admin_acme, acme):
    assert _retention_days(client_as(admin_acme), acme) == 0


@pytest.mark.django_db
def test_superadmin_retention_is_unlimited(client_as, superadmin, acme):
    assert _retention_days(client_as(superadmin), acme) == 0
