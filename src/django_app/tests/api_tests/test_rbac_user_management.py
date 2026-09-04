from importlib import import_module

import pytest
from django.apps import apps as django_apps
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- shared fixtures ----


@pytest.fixture
def role_superadmin(db):
    return Role.objects.get(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Acme Inc")


@pytest.fixture
def org_globex(db):
    return Organization.objects.create(name="Globex Corp")


@pytest.fixture
def superadmin(django_user_model, org_acme, role_superadmin):
    user = django_user_model.objects.create_user(
        email="sa@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_superadmin)
    return user


@pytest.fixture
def second_superadmin(django_user_model, org_acme, role_superadmin):
    user = django_user_model.objects.create_user(
        email="sa2@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_superadmin)
    return user


@pytest.fixture
def org_admin_acme(django_user_model, org_acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="oa@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_org_admin)
    return user


@pytest.fixture
def member_acme(django_user_model, org_acme, role_member):
    user = django_user_model.objects.create_user(
        email="m@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_member)
    return user


@pytest.fixture
def authed_client():
    def _build(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _build


# ---- endpoint URL helpers ----


USERS_LIST = "/api/admin/users/"


def user_action_url(user_id, action):
    return f"/api/admin/users/{user_id}/{action}/"


# ============================================================================
# Permission gates — UserAdminViewSet (superadmin-only user entity)
# ============================================================================


@pytest.mark.django_db
class TestPermissionsAnonymous:
    def test_list_users_anonymous_401(self):
        resp = APIClient().get(USERS_LIST)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestPermissionsMember:
    def test_list_users_403(self, authed_client, member_acme):
        resp = authed_client(member_acme).get(USERS_LIST)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_grant_superadmin_403(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            user_action_url(member_acme.pk, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPermissionsOrgAdmin:
    def test_org_admin_blocked_on_global_users_list(
        self, authed_client, org_admin_acme
    ):
        resp = authed_client(org_admin_acme).get(USERS_LIST)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_org_admin_blocked_on_grant_superadmin(
        self, authed_client, org_admin_acme, member_acme
    ):
        resp = authed_client(org_admin_acme).post(
            user_action_url(member_acme.pk, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPermissionsApiKey:
    """API key bound to a user inherits exactly that user's permissions."""

    def test_member_api_key_blocked_on_users_list(self, member_acme, issue_api_key):
        raw, _ = issue_api_key(user=member_acme, name="test-member")

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.get(USERS_LIST)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_system_api_key_acts_as_superadmin(self, issue_api_key):
        raw, _ = issue_api_key(user=None, name="system-test")

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.get(USERS_LIST)
        assert resp.status_code == status.HTTP_200_OK


# ============================================================================
# Happy paths — UserAdminViewSet
# ============================================================================


@pytest.mark.django_db
class TestListUsers:
    def test_paginated_response_shape(self, authed_client, superadmin):
        resp = authed_client(superadmin).get(USERS_LIST)
        assert resp.status_code == status.HTTP_200_OK
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}
        assert isinstance(resp.data["results"], list)

    def test_filter_by_email_substring(self, authed_client, superadmin, member_acme):
        resp = authed_client(superadmin).get(USERS_LIST + "?email=m@")
        emails = [u["email"] for u in resp.data["results"]]
        assert "m@x.com" in emails
        assert "sa@x.com" not in emails

    def test_filter_by_is_superadmin_true(self, authed_client, superadmin, member_acme):
        resp = authed_client(superadmin).get(USERS_LIST + "?is_superadmin=true")
        emails = [u["email"] for u in resp.data["results"]]
        assert "sa@x.com" in emails
        assert "m@x.com" not in emails

    def test_filter_by_organization_id(self, authed_client, superadmin, org_globex):
        resp = authed_client(superadmin).get(
            USERS_LIST + f"?organization_id={org_globex.pk}"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0


@pytest.mark.django_db
class TestCreateUser:
    def test_create_no_org(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {"email": "new@x.com", "password": "StrongPass123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["email"] == "new@x.com"
        assert resp.data["memberships"] == []
        assert resp.data["is_superadmin"] is False

    def test_create_with_org_and_role(
        self, authed_client, superadmin, org_acme, role_member
    ):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {
                "email": "new2@x.com",
                "password": "StrongPass123!",
                "organization_id": org_acme.pk,
                "role_id": role_member.pk,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert len(resp.data["memberships"]) == 1
        m = resp.data["memberships"][0]
        assert m["organization"]["id"] == org_acme.pk
        assert m["role"]["id"] == role_member.pk

    def test_create_with_org_no_role_defaults_to_member(
        self, authed_client, superadmin, org_acme, role_member
    ):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {
                "email": "new3@x.com",
                "password": "StrongPass123!",
                "organization_id": org_acme.pk,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["memberships"][0]["role"]["id"] == role_member.pk


@pytest.mark.django_db
class TestGrantRevokeSuperadmin:
    def test_grant_flips_flag(self, authed_client, superadmin, member_acme):
        resp = authed_client(superadmin).post(
            user_action_url(member_acme.pk, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is True

    def test_grant_idempotent(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            user_action_url(superadmin.pk, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is True

    def test_revoke_when_two_active_superadmins(
        self, authed_client, superadmin, second_superadmin
    ):
        resp = authed_client(superadmin).post(
            user_action_url(second_superadmin.pk, "revoke-superadmin")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is False

    def test_self_revoke_when_not_last(
        self, authed_client, superadmin, second_superadmin
    ):
        resp = authed_client(superadmin).post(
            user_action_url(superadmin.pk, "revoke-superadmin")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is False

    def test_revoke_idempotent_on_non_superadmin(
        self, authed_client, superadmin, member_acme
    ):
        resp = authed_client(superadmin).post(
            user_action_url(member_acme.pk, "revoke-superadmin")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is False


# ============================================================================
# Edge cases & invariants
# ============================================================================


@pytest.mark.django_db
class TestEmailConflict:
    def test_duplicate_email_create_user_400(self, authed_client, superadmin):
        client = authed_client(superadmin)
        client.post(
            USERS_LIST,
            {"email": "dup@x.com", "password": "StrongPass123!"},
            format="json",
        )
        resp = client.post(
            USERS_LIST,
            {"email": "dup@x.com", "password": "StrongPass123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "email_already_exists"


@pytest.mark.django_db
class TestLastSuperadminGuard:
    def test_revoke_last_superadmin_400(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            user_action_url(superadmin.pk, "revoke-superadmin")
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "last_superadmin"


# ============================================================================
# Validation tests
# ============================================================================


@pytest.mark.django_db
class TestValidation:
    def test_weak_password_400(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {"email": "weak@x.com", "password": "123"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"
        for err in resp.data.get("errors", []):
            if err["field"] == "password":
                assert err["value"] == "***"

    def test_malformed_email_400(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {"email": "not-an-email", "password": "StrongPass123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_user_id_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            user_action_url(99999, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "user_not_found"


# ============================================================================
# Non-numeric pk on detail routes → 404 from the URL resolver, not 500.
# ============================================================================


@pytest.mark.django_db
class TestNonNumericPkReturns404:
    def test_grant_superadmin_alpha_pk_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post("/api/admin/users/a/grant-superadmin/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_revoke_superadmin_alpha_pk_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post("/api/admin/users/abc/revoke-superadmin/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_grant_superadmin_negative_pk_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post("/api/admin/users/-1/grant-superadmin/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestOrganizationAdminNonNumericPkReturns404:
    def test_deactivate_alpha_pk_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            "/api/admin/organizations/abc/deactivate/"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_alpha_pk_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).patch(
            "/api/admin/organizations/abc/",
            {"name": "X"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# User activate / deactivate (superadmin)
# ============================================================================


@pytest.mark.django_db
class TestActivateDeactivate:
    def test_superadmin_deactivates_user(self, authed_client, superadmin, member_acme):
        resp = authed_client(superadmin).post(
            user_action_url(member_acme.pk, "deactivate")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_active"] is False

    def test_reactivate(self, authed_client, superadmin, member_acme):
        authed_client(superadmin).post(user_action_url(member_acme.pk, "deactivate"))
        resp = authed_client(superadmin).post(
            user_action_url(member_acme.pk, "reactivate")
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_active"] is True

    def test_cannot_deactivate_last_active_superadmin(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            user_action_url(superadmin.pk, "deactivate")
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "last_superadmin"

    def test_deactivate_denied_for_org_admin(
        self, authed_client, org_admin_acme, member_acme
    ):
        resp = authed_client(org_admin_acme).post(
            user_action_url(member_acme.pk, "deactivate")
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGrantSuperadminPurgesMemberships:
    def test_grant_purges_memberships(
        self,
        authed_client,
        superadmin,
        org_acme,
        org_globex,
        role_member,
        role_org_admin,
        django_user_model,
    ):
        target = django_user_model.objects.create_user(
            email="promote@x.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=target, org=org_acme, role=role_org_admin)
        OrganizationUser.objects.create(user=target, org=org_globex, role=role_member)

        resp = authed_client(superadmin).post(
            user_action_url(target.pk, "grant-superadmin")
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is True
        assert resp.data["memberships"] == []
        assert not OrganizationUser.objects.filter(user=target).exists()

    def test_grant_on_existing_superadmin_leaves_rows(
        self, authed_client, superadmin, org_acme, role_member, django_user_model
    ):
        """Already a superadmin: the method short-circuits before any write, so
        a pre-existing row survives. The data migration reconciles those."""
        target = django_user_model.objects.create_user(
            email="already@x.com", password="StrongPass123!", is_superadmin=True
        )
        OrganizationUser.objects.create(user=target, org=org_acme, role=role_member)

        resp = authed_client(superadmin).post(
            user_action_url(target.pk, "grant-superadmin")
        )

        assert resp.status_code == status.HTTP_200_OK
        assert OrganizationUser.objects.filter(user=target).count() == 1

    def test_revoke_does_not_restore_memberships(
        self, authed_client, superadmin, org_acme, role_org_admin, django_user_model
    ):
        target = django_user_model.objects.create_user(
            email="roundtrip@x.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=target, org=org_acme, role=role_org_admin)

        authed_client(superadmin).post(user_action_url(target.pk, "grant-superadmin"))
        resp = authed_client(superadmin).post(
            user_action_url(target.pk, "revoke-superadmin")
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superadmin"] is False
        assert resp.data["memberships"] == []


@pytest.mark.django_db
class TestSuperadminMembershipMigration:
    def test_purges_lesser_roles_but_keeps_bootstrap(
        self,
        org_acme,
        role_member,
        role_org_admin,
        role_superadmin,
        django_user_model,
    ):
        sa_lesser = django_user_model.objects.create_user(
            email="legacy-sa@x.com", password="StrongPass123!", is_superadmin=True
        )
        sa_bootstrap = django_user_model.objects.create_user(
            email="bootstrap-sa@x.com", password="StrongPass123!", is_superadmin=True
        )
        ordinary = django_user_model.objects.create_user(
            email="ordinary@x.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(
            user=sa_lesser, org=org_acme, role=role_org_admin
        )
        OrganizationUser.objects.create(
            user=sa_bootstrap, org=org_acme, role=role_superadmin
        )
        OrganizationUser.objects.create(user=ordinary, org=org_acme, role=role_member)

        module = import_module("tables.migrations.0211_purge_superadmin_memberships")
        module.purge_superadmin_memberships(django_apps, None)

        assert not OrganizationUser.objects.filter(user=sa_lesser).exists()
        assert OrganizationUser.objects.filter(user=sa_bootstrap).exists()
        assert OrganizationUser.objects.filter(user=ordinary).exists()

        module.purge_superadmin_memberships(django_apps, None)
        assert OrganizationUser.objects.filter(user=sa_bootstrap).count() == 1
        assert OrganizationUser.objects.filter(user=ordinary).count() == 1
