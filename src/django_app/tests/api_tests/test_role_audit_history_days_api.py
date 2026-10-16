import pytest
from rest_framework import status

from rbac.models import Role
from rbac.models.role import AUDIT_HISTORY_DAYS_MAX
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ROLES_URL = "/api/admin/roles/"


def _detail_url(role):
    return f"{ROLES_URL}{role.id}/"


@pytest.mark.django_db
def test_create_persists_audit_history_days(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Auditor", "permissions": [], "audit_history_days": 90},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert response.json()["audit_history_days"] == 90
    assert Role.objects.get(pk=response.json()["id"]).audit_history_days == 90


@pytest.mark.django_db
def test_create_without_audit_history_days_is_unlimited(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL, {"org_id": acme.id, "name": "Default", "permissions": []}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["audit_history_days"] == 0


@pytest.mark.django_db
def test_patch_persists_audit_history_days(client_as, admin_acme, acme):
    role = Role.objects.create(name="Editable", org=acme, is_built_in=False)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"audit_history_days": AUDIT_HISTORY_DAYS_MAX}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert response.json()["audit_history_days"] == AUDIT_HISTORY_DAYS_MAX
    role.refresh_from_db()
    assert role.audit_history_days == AUDIT_HISTORY_DAYS_MAX
    assert role.name == "Editable"


@pytest.mark.django_db
def test_get_returns_audit_history_days(client_as, admin_acme, acme):
    role = Role.objects.create(name="Reader", org=acme, is_built_in=False, audit_history_days=7)

    detail = client_as(admin_acme).get(_detail_url(role)).json()
    listed = client_as(admin_acme).get(ROLES_URL).json()

    assert detail["audit_history_days"] == 7
    assert next(row for row in listed["results"] if row["id"] == role.id)["audit_history_days"] == 7
    assert all(row["audit_history_days"] == 0 for row in listed["built_in_roles"])


@pytest.mark.django_db
@pytest.mark.parametrize("value", [-1, AUDIT_HISTORY_DAYS_MAX + 1, "30", True, None, 1.5])
def test_create_rejects_invalid_audit_history_days(client_as, admin_acme, acme, value):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Invalid", "permissions": [], "audit_history_days": value},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Role.objects.filter(org=acme, name="Invalid").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("value", [-1, AUDIT_HISTORY_DAYS_MAX + 1, "30", True])
def test_patch_rejects_invalid_audit_history_days(client_as, admin_acme, acme, value):
    role = Role.objects.create(name="Untouched", org=acme, is_built_in=False, audit_history_days=5)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"audit_history_days": value}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    role.refresh_from_db()
    assert role.audit_history_days == 5


@pytest.mark.django_db
def test_patch_role_of_another_org_is_404(client_as, admin_acme, beta):
    role = Role.objects.create(name="Beta Role", org=beta, is_built_in=False, audit_history_days=5)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"audit_history_days": 1}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    role.refresh_from_db()
    assert role.audit_history_days == 5


@pytest.mark.django_db
def test_built_in_role_audit_history_days_cannot_be_edited(client_as, admin_acme, role_member):
    response = client_as(admin_acme).patch(
        _detail_url(role_member), {"audit_history_days": 30}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["code"] == "built_in_role_immutable"
    role_member.refresh_from_db()
    assert role_member.audit_history_days == 0
