import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import OrganizationConfig, OrganizationUser

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

PASSWORD = "StrongPass123!"


@pytest.fixture
def admin_in_two_orgs(admin_acme, beta, role_member):
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    return admin_acme


def _jwt_client(user):
    # Key creation is bound to the caller's session token, which force_authenticate lacks.
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _login(client, email, password):
    return client.post(reverse("login"), {"email": email, "password": password}, format="json")


def _summary(events):
    return sorted((event.action, event.org_id, event.actor_email) for event in events)


def test_login_success_records_signed_in_in_each_org(
    api_client, admin_in_two_orgs, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _login(api_client, admin_in_two_orgs.email, PASSWORD)

    assert response.status_code == status.HTTP_200_OK
    email = admin_in_two_orgs.email
    assert _summary(sent_events) == sorted(
        [("signed_in", acme.id, email), ("signed_in", beta.id, email)]
    )
    assert {event.actor_user_id for event in sent_events} == {admin_in_two_orgs.id}


def test_login_wrong_password_records_sign_in_failed(
    api_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _login(api_client, admin_acme.email, "not-the-password")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert _summary(sent_events) == [("sign_in_failed", acme.id, admin_acme.email)]
    assert "not-the-password" not in repr(sent_events)


def test_login_unknown_email_records_nothing(
    api_client, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _login(api_client, "nobody@example.com", PASSWORD)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert sent_events == []


def test_login_with_missing_password_records_nothing(
    api_client, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(reverse("login"), {"email": admin_acme.email}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert sent_events == []


def test_logout_records_signed_out(
    client_as, admin_in_two_orgs, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_in_two_orgs).post(reverse("logout"))

    assert response.status_code == status.HTTP_205_RESET_CONTENT
    email = admin_in_two_orgs.email
    assert _summary(sent_events) == sorted(
        [("signed_out", acme.id, email), ("signed_out", beta.id, email)]
    )


def test_admin_password_reset_records_password_reset_in_each_target_org(
    client_as,
    superadmin,
    admin_in_two_orgs,
    acme,
    beta,
    sent_events,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(superadmin).post(
            "/api/auth/admin/password-reset/",
            {"user_id": admin_in_two_orgs.id, "new_password": "BrandNewPass456!"},
            format="json",
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert sorted((event.org_id, event.actor_email) for event in sent_events) == sorted(
        [(acme.id, superadmin.email), (beta.id, superadmin.email)]
    )
    for event in sent_events:
        assert (event.action, event.target_type, event.target_name) == (
            "password_reset",
            "user",
            admin_in_two_orgs.email,
        )


def test_change_role_records_updated_member_with_previous_role(
    client_as,
    admin_acme,
    acme,
    role_member,
    role_viewer,
    django_user_model,
    sent_events,
    django_capture_on_commit_callbacks,
):
    bob = django_user_model.objects.create_user(email="bob@example.com", password=PASSWORD)
    membership = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_acme).patch(
            f"/api/admin/memberships/{membership.id}/",
            {"role_id": role_viewer.id},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK
    (event,) = sent_events
    assert (event.action, event.org_id, event.actor_email) == (
        "updated",
        acme.id,
        admin_acme.email,
    )
    assert (event.target_type, event.target_name) == ("member", "bob@example.com")
    assert event.previous_name == role_member.name


def test_change_role_to_the_same_role_records_nothing(
    client_as,
    admin_acme,
    acme,
    role_member,
    django_user_model,
    sent_events,
    django_capture_on_commit_callbacks,
):
    bob = django_user_model.objects.create_user(email="bob@example.com", password=PASSWORD)
    membership = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)

    with django_capture_on_commit_callbacks(execute=True):
        client_as(admin_acme).patch(
            f"/api/admin/memberships/{membership.id}/",
            {"role_id": role_member.id},
            format="json",
        )

    assert sent_events == []


def test_add_member_records_created_member(
    client_as,
    admin_acme,
    acme,
    role_member,
    django_user_model,
    sent_events,
    django_capture_on_commit_callbacks,
):
    django_user_model.objects.create_user(email="new@example.com", password=PASSWORD)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_acme).post(
            "/api/admin/memberships/",
            {"org_id": acme.id, "email": "new@example.com", "role_id": role_member.id},
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED
    (event,) = sent_events
    assert (event.action, event.org_id, event.target_type, event.target_name) == (
        "created",
        acme.id,
        "member",
        "new@example.com",
    )


def test_remove_member_records_deleted_member(
    client_as,
    admin_acme,
    acme,
    role_member,
    django_user_model,
    sent_events,
    django_capture_on_commit_callbacks,
):
    bob = django_user_model.objects.create_user(email="bob@example.com", password=PASSWORD)
    membership = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_acme).delete(f"/api/admin/memberships/{membership.id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    (event,) = sent_events
    assert (event.action, event.org_id, event.target_type, event.target_name) == (
        "deleted",
        acme.id,
        "member",
        "bob@example.com",
    )


def test_role_create_update_and_delete_record_the_role_name(
    client_as, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    client = client_as(admin_acme)
    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(
            "/api/admin/roles/",
            {"org_id": acme.id, "name": "Auditor", "description": "", "permissions": []},
            format="json",
        )
    assert created.status_code == status.HTTP_201_CREATED
    role_id = created.json()["id"]
    with django_capture_on_commit_callbacks(execute=True):
        client.patch(f"/api/admin/roles/{role_id}/", {"description": "Reads"}, format="json")
    with django_capture_on_commit_callbacks(execute=True):
        deleted = client.delete(f"/api/admin/roles/{role_id}/")
    assert deleted.status_code == status.HTTP_200_OK

    assert [(e.action, e.target_type, e.target_name, e.org_id) for e in sent_events] == [
        ("created", "role", "Auditor", acme.id),
        ("updated", "role", "Auditor", acme.id),
        ("deleted", "role", "Auditor", acme.id),
    ]


def test_api_key_create_records_created(
    admin_in_two_orgs, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _jwt_client(admin_in_two_orgs).post(
            "/api/profile/api-keys/", {"name": "mcp-laptop"}, format="json"
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert sorted((e.action, e.org_id, e.target_type, e.target_name) for e in sent_events) == (
        sorted(
            [
                ("created", acme.id, "api key", "mcp-laptop"),
                ("created", beta.id, "api key", "mcp-laptop"),
            ]
        )
    )


def test_api_key_revoke_records_updated_once(
    admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    client = _jwt_client(admin_acme)
    key_id = client.post("/api/profile/api-keys/", {"name": "ci"}, format="json").json()["id"]
    sent_events.clear()

    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/profile/api-keys/{key_id}/revoke/")
        client.post(f"/api/profile/api-keys/{key_id}/revoke/")

    assert [(e.action, e.org_id, e.target_name) for e in sent_events] == [
        ("updated", acme.id, "ci")
    ]


def test_retention_change_records_updated_organization(
    client_as, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    OrganizationConfig.objects.create(org=acme)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_acme).patch(
            f"/api/admin/organizations/{acme.id}/retention/",
            {"sessions_days": 90},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK
    (event,) = sent_events
    assert (event.action, event.org_id, event.target_type, event.target_name) == (
        "updated",
        acme.id,
        "organization",
        acme.name,
    )


def test_organization_rename_records_renamed_with_previous_name(
    client_as, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    previous_name = acme.name

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as(admin_acme).patch(
            f"/api/admin/organizations/{acme.id}/", {"name": "Acme Renamed"}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK
    (event,) = sent_events
    assert (event.action, event.target_type, event.target_name, event.previous_name) == (
        "renamed",
        "organization",
        "Acme Renamed",
        previous_name,
    )
