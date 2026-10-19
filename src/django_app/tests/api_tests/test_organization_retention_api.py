import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.access.gates import RestrictApiKeyToUserKeyReads
from rbac.models import OrganizationRetention, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission
from src.shared.retention import DataType, RetentionPolicy, RetentionRule

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def retention_url(org_id):
    return f"/api/admin/organizations/{org_id}/retention/"


@pytest.fixture(autouse=True)
def retention_policy(settings):
    settings.RETENTION_POLICY = RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=None),
            DataType.CONVERSATIONS: RetentionRule(default_days=90, max_days=180),
            DataType.AUDIT: RetentionRule(default_days=365, max_days=None),
        }
    )
    return settings.RETENTION_POLICY


@pytest.fixture
def cap_sessions_at_90(settings):
    settings.RETENTION_POLICY = RetentionPolicy(
        rules={
            **settings.RETENTION_POLICY.rules,
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=90),
        }
    )


def make_custom_role_user(django_user_model, org, email, permissions):
    role = Role.objects.create(name=f"custom-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type="organizations", permissions=int(permissions)
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


# ---- PATCH ----


@pytest.mark.django_db
def test_org_admin_sets_own_org_retention(client_as, admin_acme, acme):
    response = client_as(admin_acme).patch(
        retention_url(acme.id),
        {"sessions_days": 90, "conversations_days": 180, "audit_days": 0},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["sessions_days"] == 90
    assert body["sessions_effective_days"] == 90
    assert body["conversations_days"] == 180
    assert body["conversations_effective_days"] == 180
    assert body["audit_days"] == 0
    assert body["audit_effective_days"] == 0
    assert body["updated_by"]["id"] == admin_acme.id
    assert body["updated_at"] is not None

    stored = OrganizationRetention.objects.get(org=acme)
    assert (stored.sessions_days, stored.conversations_days, stored.audit_days) == (90, 180, 0)
    assert stored.updated_by_id == admin_acme.id


@pytest.mark.django_db
def test_patch_changes_only_the_fields_sent(client_as, admin_acme, acme):
    OrganizationRetention.objects.create(
        org=acme, sessions_days=90, conversations_days=30, audit_days=180
    )

    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"conversations_days": 180}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    stored = OrganizationRetention.objects.get(org=acme)
    assert (stored.sessions_days, stored.conversations_days, stored.audit_days) == (90, 180, 180)


@pytest.mark.django_db
def test_null_resets_to_default(client_as, admin_acme, acme):
    OrganizationRetention.objects.create(org=acme, sessions_days=90, audit_days=180)

    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": None}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["sessions_days"] is None
    assert response.json()["sessions_effective_days"] == 30
    stored = OrganizationRetention.objects.get(org=acme)
    assert stored.sessions_days is None
    assert stored.audit_days == 180


@pytest.mark.django_db
@pytest.mark.parametrize("value", [45, -1, "abc", "30", 30.0, True, 36500])
def test_rejects_value_outside_list(client_as, admin_acme, acme, value):
    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": value}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert response.json()["message"] == "Invalid sessions_days."
    assert response.json()["errors"] == [
        {
            "field": "sessions_days",
            "value": value,
            "reason": "Must be one of [0, 30, 90, 180, 365], or null for the instance default.",
        }
    ]
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("value", [365, 180, 0])
def test_rejects_value_above_cap(client_as, admin_acme, acme, cap_sessions_at_90, value):
    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": value}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "sessions_days" in response.json()["message"]
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("value", [30, 90])
def test_accepts_value_at_or_below_cap(client_as, admin_acme, acme, cap_sessions_at_90, value):
    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": value}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert OrganizationRetention.objects.get(org=acme).sessions_days == value


@pytest.mark.django_db
def test_stored_value_above_a_lowered_cap_can_be_saved_unchanged(
    client_as, admin_acme, acme, cap_sessions_at_90
):
    # Chosen while sessions had no cap; the cap was lowered afterwards.
    OrganizationRetention.objects.create(org=acme, sessions_days=365, conversations_days=90)

    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": 365, "conversations_days": 30}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["sessions_effective_days"] == 90
    stored = OrganizationRetention.objects.get(org=acme)
    assert (stored.sessions_days, stored.conversations_days) == (365, 30)


@pytest.mark.django_db
def test_stored_value_does_not_admit_another_value_above_the_cap(
    client_as, admin_acme, acme, cap_sessions_at_90
):
    OrganizationRetention.objects.create(org=acme, sessions_days=365)

    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": 180}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert OrganizationRetention.objects.get(org=acme).sessions_days == 365


@pytest.mark.django_db
@pytest.mark.parametrize("value", [30.0, "30"])
def test_non_integer_equal_to_the_stored_value_is_rejected(client_as, admin_acme, acme, value):
    OrganizationRetention.objects.create(org=acme, sessions_days=30)

    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": value}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["errors"][0]["field"] == "sessions_days"


@pytest.mark.django_db
def test_one_invalid_field_rejects_the_whole_body(client_as, admin_acme, acme):
    response = client_as(admin_acme).patch(
        retention_url(acme.id), {"sessions_days": 90, "audit_days": 45}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "audit_days" in response.json()["message"]
    assert [error["field"] for error in response.json()["errors"]] == ["audit_days"]
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"unknown_days": 30}])
def test_rejects_body_without_a_retention_field(client_as, admin_acme, acme, body):
    response = client_as(admin_acme).patch(retention_url(acme.id), body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not OrganizationRetention.objects.filter(org=acme).exists()


# ---- GET ----


@pytest.mark.django_db
def test_get_without_row_returns_nulls_and_defaults(client_as, admin_acme, acme):
    response = client_as(admin_acme).get(retention_url(acme.id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["org_id"] == acme.id
    assert body["sessions_days"] is None
    assert body["sessions_effective_days"] == 30
    assert body["conversations_days"] is None
    assert body["conversations_effective_days"] == 90
    assert body["audit_days"] is None
    assert body["audit_effective_days"] == 365
    assert body["updated_at"] is None
    assert body["updated_by"] is None
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_get_reports_effective_days_clamped_to_a_lowered_cap(
    client_as, admin_acme, acme, cap_sessions_at_90
):
    # Chosen while sessions had no cap; the cap was lowered afterwards.
    OrganizationRetention.objects.create(org=acme, sessions_days=365)

    response = client_as(admin_acme).get(retention_url(acme.id))

    assert response.json()["sessions_days"] == 365
    assert response.json()["sessions_effective_days"] == 90


@pytest.mark.django_db
def test_get_exposes_retention_policy(client_as, admin_acme, acme):
    response = client_as(admin_acme).get(retention_url(acme.id))

    assert response.json()["retention_policy"] == {
        "sessions": {"default_days": 30, "max_days": None, "allowed": [0, 30, 90, 180, 365]},
        "conversations": {"default_days": 90, "max_days": 180, "allowed": [30, 90, 180]},
        "audit": {"default_days": 365, "max_days": None, "allowed": [0, 30, 90, 180, 365]},
    }


# ---- access ----


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch"])
def test_other_org_returns_404(client_as, admin_acme, beta, method):
    OrganizationRetention.objects.create(org=beta, sessions_days=180)
    client = client_as(admin_acme)

    if method == "get":
        response = client.get(retention_url(beta.id))
    else:
        response = client.patch(retention_url(beta.id), {"sessions_days": 30}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "organization_not_found"
    assert OrganizationRetention.objects.get(org=beta).sessions_days == 180


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch"])
def test_member_without_organizations_permission_is_denied(client_as, member_only, acme, method):
    client = client_as(member_only)

    if method == "get":
        response = client.get(retention_url(acme.id))
    else:
        response = client.patch(retention_url(acme.id), {"sessions_days": 30}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["code"] == "permission_denied"
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_patch_with_read_but_no_update_is_403(
    client_as, django_user_model, acme, beta, role_org_admin
):
    # Org Admin of beta passes the door gate; the 403 comes from the per-org check on acme.
    reader = make_custom_role_user(
        django_user_model, acme, "retention-reader@example.com", Permission.READ
    )
    OrganizationUser.objects.create(user=reader, org=beta, role=role_org_admin)

    get_response = client_as(reader).get(retention_url(acme.id))
    patch_response = client_as(reader).patch(
        retention_url(acme.id), {"sessions_days": 30}, format="json"
    )

    assert get_response.status_code == status.HTTP_200_OK
    assert patch_response.status_code == status.HTTP_403_FORBIDDEN
    assert patch_response.json()["code"] == "permission_denied"
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_write_without_read_grant_can_patch(client_as, django_user_model, acme):
    writer = make_custom_role_user(
        django_user_model, acme, "retention-writer@example.com", Permission.UPDATE
    )

    response = client_as(writer).patch(retention_url(acme.id), {"audit_days": 90}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert OrganizationRetention.objects.get(org=acme).audit_days == 90


@pytest.mark.django_db
def test_superadmin_reads_and_updates_any_org(client_as, superadmin, beta):
    client = client_as(superadmin)

    patch_response = client.patch(retention_url(beta.id), {"sessions_days": 180}, format="json")
    get_response = client.get(retention_url(beta.id))

    assert patch_response.status_code == status.HTTP_200_OK
    assert get_response.json()["sessions_days"] == 180
    assert OrganizationRetention.objects.get(org=beta).updated_by_id == superadmin.id


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch"])
def test_superadmin_gets_404_for_missing_org(client_as, superadmin, method):
    client = client_as(superadmin)

    if method == "get":
        response = client.get(retention_url(999_999))
    else:
        response = client.patch(retention_url(999_999), {"sessions_days": 30}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "organization_not_found"


@pytest.mark.django_db
def test_unauthenticated_request_is_401(acme):
    response = APIClient().get(retention_url(acme.id))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_user_api_key_cannot_patch(issue_api_key, admin_acme, acme):
    raw_key, _ = issue_api_key(user=admin_acme, name="retention-user-key")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = client.patch(retention_url(acme.id), {"sessions_days": 30}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["message"] == RestrictApiKeyToUserKeyReads.write_message
    assert not OrganizationRetention.objects.filter(org=acme).exists()
