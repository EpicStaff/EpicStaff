import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
)
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
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


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


def org_users_list_url(org_id):
    return f"/api/admin/organizations/{org_id}/users/"


def org_user_detail_url(org_id, user_id):
    return f"/api/admin/organizations/{org_id}/users/{user_id}/"


# ============================================================================
# Permission gates
# ============================================================================


@pytest.mark.django_db
class TestPermissionsAnonymous:
    def test_list_users_anonymous_401(self):
        resp = APIClient().get(USERS_LIST)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_org_users_anonymous_401(self, org_acme):
        resp = APIClient().get(org_users_list_url(org_acme.pk))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestPermissionsMember:
    """A plain Member must not reach any Story 5 endpoint."""

    def test_list_users_403(self, authed_client, member_acme):
        resp = authed_client(member_acme).get(USERS_LIST)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_list_org_users_403(self, authed_client, member_acme, org_acme):
        resp = authed_client(member_acme).get(org_users_list_url(org_acme.pk))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_grant_superadmin_403(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            user_action_url(member_acme.pk, "grant-superadmin")
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPermissionsOrgAdmin:
    """Org Admin can hit org-scoped endpoints for their own org only."""

    def test_org_admin_lists_own_org_members(
        self, authed_client, org_admin_acme, org_acme
    ):
        resp = authed_client(org_admin_acme).get(org_users_list_url(org_acme.pk))
        assert resp.status_code == status.HTTP_200_OK

    def test_org_admin_blocked_on_other_org(
        self, authed_client, org_admin_acme, org_globex
    ):
        resp = authed_client(org_admin_acme).get(org_users_list_url(org_globex.pk))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

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
        """System keys resolve to SystemServicePrincipal (is_superadmin=True)
        and pass superadmin-gated endpoints."""
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
        # superadmin is in org_acme, not org_globex
        resp = authed_client(superadmin).get(
            USERS_LIST + f"?organization_id={org_globex.pk}"
        )
        assert resp.status_code == status.HTTP_200_OK
        # No users in org_globex yet
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
# Happy paths — OrganizationMembershipAdminViewSet
# ============================================================================


@pytest.mark.django_db
class TestListOrgMembers:
    def test_response_shape(self, authed_client, superadmin, org_acme):
        resp = authed_client(superadmin).get(org_users_list_url(org_acme.pk))
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)
        assert all("membership" in m for m in resp.data)

    def test_org_admin_sees_own_org(
        self, authed_client, org_admin_acme, org_acme, member_acme
    ):
        resp = authed_client(org_admin_acme).get(org_users_list_url(org_acme.pk))
        emails = [m["email"] for m in resp.data]
        assert "m@x.com" in emails
        assert "oa@x.com" in emails

    def test_filter_by_role(self, authed_client, superadmin, org_acme, member_acme):
        resp = authed_client(superadmin).get(
            org_users_list_url(org_acme.pk) + f"?role={BuiltInRole.MEMBER}"
        )
        emails = [m["email"] for m in resp.data]
        assert "m@x.com" in emails
        assert "sa@x.com" not in emails


@pytest.mark.django_db
class TestAddMembership:
    def test_create_and_link(
        self, authed_client, org_admin_acme, org_acme, role_member
    ):
        resp = authed_client(org_admin_acme).post(
            org_users_list_url(org_acme.pk),
            {
                "email": "fresh@x.com",
                "password": "StrongPass123!",
                "role_id": role_member.pk,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["email"] == "fresh@x.com"

    def test_create_and_link_defaults_to_member_role(
        self, authed_client, org_admin_acme, org_acme, role_member
    ):
        resp = authed_client(org_admin_acme).post(
            org_users_list_url(org_acme.pk),
            {"email": "fresh2@x.com", "password": "StrongPass123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["membership"]["role"]["id"] == role_member.pk


@pytest.mark.django_db
class TestChangeRole:
    def test_promote_member_to_org_admin(
        self,
        authed_client,
        superadmin,
        org_acme,
        member_acme,
        role_org_admin,
    ):
        resp = authed_client(superadmin).patch(
            org_user_detail_url(org_acme.pk, member_acme.pk),
            {"role_id": role_org_admin.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["membership"]["role"]["id"] == role_org_admin.pk

    def test_idempotent_same_role(
        self, authed_client, superadmin, org_acme, member_acme, role_member
    ):
        resp = authed_client(superadmin).patch(
            org_user_detail_url(org_acme.pk, member_acme.pk),
            {"role_id": role_member.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRemoveMembership:
    def test_happy_path(self, authed_client, superadmin, org_acme, member_acme):
        resp = authed_client(superadmin).delete(
            org_user_detail_url(org_acme.pk, member_acme.pk)
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not OrganizationUser.objects.filter(
            user=member_acme, org=org_acme
        ).exists()

    def test_self_removal_allowed(self, authed_client, member_acme, org_acme):
        # member can't reach this endpoint per permissions, but add a
        # non-last Org Admin who self-removes
        pass  # covered by TestSelfRemovalOrgAdminNotLast below


@pytest.mark.django_db
class TestSelfRemovalOrgAdminNotLast:
    def test_org_admin_removes_self_when_not_last(
        self,
        authed_client,
        django_user_model,
        org_acme,
        role_org_admin,
    ):
        oa1 = django_user_model.objects.create_user(
            email="oa1@x.com", password="StrongPass123!"
        )
        oa2 = django_user_model.objects.create_user(
            email="oa2@x.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=oa1, org=org_acme, role=role_org_admin)
        OrganizationUser.objects.create(user=oa2, org=org_acme, role=role_org_admin)

        resp = authed_client(oa1).delete(org_user_detail_url(org_acme.pk, oa1.pk))
        assert resp.status_code == status.HTTP_204_NO_CONTENT


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

    def test_duplicate_email_add_membership_create_mode_400(
        self, authed_client, org_admin_acme, org_acme, member_acme, role_member
    ):
        resp = authed_client(org_admin_acme).post(
            org_users_list_url(org_acme.pk),
            {
                "email": member_acme.email,
                "password": "StrongPass123!",
                "role_id": role_member.pk,
            },
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


@pytest.mark.django_db
class TestLastOrgAdminGuard:
    def test_remove_last_org_admin_400(
        self, authed_client, superadmin, org_acme, org_admin_acme
    ):
        # org_admin_acme is the only Org Admin in org_acme
        resp = authed_client(superadmin).delete(
            org_user_detail_url(org_acme.pk, org_admin_acme.pk)
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "last_org_admin"

    def test_demote_last_org_admin_400(
        self,
        authed_client,
        superadmin,
        org_acme,
        org_admin_acme,
        role_member,
    ):
        resp = authed_client(superadmin).patch(
            org_user_detail_url(org_acme.pk, org_admin_acme.pk),
            {"role_id": role_member.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "last_org_admin"


@pytest.mark.django_db
class TestZeroOrgsSteadyState:
    def test_user_with_zero_memberships_can_login(
        self, authed_client, superadmin, member_acme, org_acme
    ):
        # Remove member's only membership
        authed_client(superadmin).delete(
            org_user_detail_url(org_acme.pk, member_acme.pk)
        )
        # /api/profile/ should still return the user, with empty memberships[]
        resp = authed_client(member_acme).get("/api/profile/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["memberships"] == []


# ============================================================================
# Validation tests
# ============================================================================


@pytest.mark.django_db
class TestValidation:
    def test_add_membership_missing_email_400(
        self, authed_client, superadmin, org_acme, role_member
    ):
        resp = authed_client(superadmin).post(
            org_users_list_url(org_acme.pk),
            {"role_id": role_member.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_weak_password_400(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            USERS_LIST,
            {"email": "weak@x.com", "password": "123"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"
        # Password should be redacted in the echo
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

    def test_unknown_org_id_404(self, authed_client, superadmin, role_member):
        resp = authed_client(superadmin).post(
            org_users_list_url(99999),
            {
                "email": "new@x.com",
                "password": "StrongPass123!",
                "role_id": role_member.pk,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_role_id_on_create_404(self, authed_client, superadmin, org_acme):
        resp = authed_client(superadmin).post(
            org_users_list_url(org_acme.pk),
            {
                "email": "fresh-role-404@x.com",
                "password": "StrongPass123!",
                "role_id": 99999,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "role_not_found"


# ============================================================================
# Variant A regression: non-numeric pk on detail routes must 404 from the
# URL resolver, not 500 from int(pk) ValueError.
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
# Batch assign-users endpoint
# ============================================================================


def org_assign_users_url(org_id):
    return f"/api/admin/organizations/{org_id}/assign-users/"


@pytest.fixture
def detached_user(django_user_model):
    """A user with no membership in any org — eligible to be assigned."""
    return django_user_model.objects.create_user(
        email="detached@x.com", password="StrongPass123!"
    )


@pytest.fixture
def detached_user_2(django_user_model):
    return django_user_model.objects.create_user(
        email="detached2@x.com", password="StrongPass123!"
    )


@pytest.mark.django_db
class TestAssignUsersHappyPath:
    def test_superadmin_assigns_two_new_users_200(
        self,
        authed_client,
        superadmin,
        org_globex,
        detached_user,
        detached_user_2,
        role_member,
        role_org_admin,
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                    {"user_id": detached_user_2.pk, "role_id": role_org_admin.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "created" in resp.data
        assert "updated" in resp.data
        assert len(resp.data["created"]) == 2
        assert resp.data["updated"] == []

    def test_org_admin_assigns_two_new_users_200(
        self,
        authed_client,
        org_admin_acme,
        org_acme,
        detached_user,
        detached_user_2,
        role_member,
    ):
        resp = authed_client(org_admin_acme).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                    {"user_id": detached_user_2.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["created"]) == 2
        assert resp.data["updated"] == []

    def test_response_preserves_submission_order_in_created(
        self,
        authed_client,
        superadmin,
        org_globex,
        detached_user,
        detached_user_2,
        role_member,
    ):
        # Submit user_2 first, then user_1. Both are new memberships.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {
                "assignments": [
                    {"user_id": detached_user_2.pk, "role_id": role_member.pk},
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        ids_in_response = [m["id"] for m in resp.data["created"]]
        assert ids_in_response == [detached_user_2.pk, detached_user.pk]


@pytest.mark.django_db
class TestAssignUsersUpsert:
    """Reassignment branch: rows whose (user_id, org_id) already exists
    update the role instead of being rejected."""

    def test_existing_membership_role_updated(
        self,
        authed_client,
        superadmin,
        org_acme,
        member_acme,
        role_viewer,
    ):
        # member_acme is currently Member of org_acme. Reassign to Viewer.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": member_acme.pk, "role_id": role_viewer.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == []
        assert len(resp.data["updated"]) == 1
        assert resp.data["updated"][0]["membership"]["role"]["id"] == role_viewer.pk
        # Confirm the DB row was actually updated.
        membership = OrganizationUser.objects.get(user=member_acme, org=org_acme)
        assert membership.role_id == role_viewer.pk

    def test_no_op_same_role(
        self,
        authed_client,
        superadmin,
        org_acme,
        member_acme,
        role_member,
    ):
        # member_acme is already Member; same role re-submitted is a no-op
        # but still returned in `updated`.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": member_acme.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["created"] == []
        assert len(resp.data["updated"]) == 1

    def test_mixed_create_and_reassign(
        self,
        authed_client,
        superadmin,
        org_acme,
        member_acme,
        detached_user,
        role_viewer,
    ):
        # member_acme already in org_acme as Member → reassign to Viewer.
        # detached_user not in org_acme → create as Viewer.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_viewer.pk},
                    {"user_id": member_acme.pk, "role_id": role_viewer.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["created"]) == 1
        assert len(resp.data["updated"]) == 1
        assert resp.data["created"][0]["id"] == detached_user.pk
        assert resp.data["updated"][0]["id"] == member_acme.pk


@pytest.mark.django_db
class TestAssignUsersNetEffectOrgAdminGuard:
    """Net-effect last-Org-Admin check: the batch as a whole must not
    leave the org with zero Org Admins."""

    def test_demote_only_org_admin_400(
        self,
        authed_client,
        superadmin,
        org_acme,
        org_admin_acme,
        role_member,
    ):
        # org_admin_acme is the only Org Admin in org_acme. Demoting them
        # in a batch must be refused.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": org_admin_acme.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "last_org_admin"

    def test_demote_org_admin_when_other_promoted_in_same_batch_200(
        self,
        authed_client,
        superadmin,
        org_acme,
        org_admin_acme,
        member_acme,
        role_member,
        role_org_admin,
    ):
        # Demote the existing Org Admin AND promote member_acme to Org Admin
        # in the same batch. Net effect: org still has at least one Org Admin.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": org_admin_acme.pk, "role_id": role_member.pk},
                    {"user_id": member_acme.pk, "role_id": role_org_admin.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestAssignUsersConflicts:
    def test_unknown_user_id_404(
        self, authed_client, superadmin, org_globex, role_member
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"user_id": 99999, "role_id": role_member.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "user_not_found"

    def test_unknown_role_id_404(
        self, authed_client, superadmin, org_globex, detached_user
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"user_id": detached_user.pk, "role_id": 99999}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "role_not_found"

    def test_assigning_global_superadmin_role_400(
        self,
        authed_client,
        superadmin,
        org_globex,
        detached_user,
        role_superadmin,
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_superadmin.pk}
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_role_assignment"

    def test_assigning_custom_role_from_other_org_400(
        self,
        authed_client,
        superadmin,
        org_acme,
        org_globex,
        detached_user,
    ):
        other_role = Role.objects.create(
            name="Custom-Other", is_built_in=False, org=org_globex
        )
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_acme.pk),
            {"assignments": [{"user_id": detached_user.pk, "role_id": other_role.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid_role_assignment"

    def test_unknown_org_id_404(
        self, authed_client, superadmin, detached_user, role_member
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(99999),
            {"assignments": [{"user_id": detached_user.pk, "role_id": role_member.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "organization_not_found"


@pytest.mark.django_db
class TestAssignUsersValidation:
    def test_missing_assignments_400(self, authed_client, superadmin, org_globex):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk), {}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_empty_assignments_400(self, authed_client, superadmin, org_globex):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_too_many_assignments_400(
        self, authed_client, superadmin, org_globex, role_member
    ):
        # 101 items — exceeds the cap.
        items = [{"user_id": i, "role_id": role_member.pk} for i in range(1, 102)]
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": items},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_missing_role_id_per_row_400(
        self, authed_client, superadmin, org_globex, detached_user
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"user_id": detached_user.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_missing_user_id_per_row_400(
        self, authed_client, superadmin, org_globex, role_member
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"role_id": role_member.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_duplicate_user_id_in_batch_400(
        self,
        authed_client,
        superadmin,
        org_globex,
        detached_user,
        role_member,
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"

    def test_non_int_role_id_400(
        self, authed_client, superadmin, org_globex, detached_user
    ):
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"user_id": detached_user.pk, "role_id": "abc"}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "invalid"


@pytest.mark.django_db
class TestAssignUsersPermissions:
    def test_anonymous_401(self, org_acme):
        resp = APIClient().post(
            org_assign_users_url(org_acme.pk),
            {"assignments": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_403(
        self, authed_client, member_acme, org_acme, detached_user, role_member
    ):
        resp = authed_client(member_acme).post(
            org_assign_users_url(org_acme.pk),
            {"assignments": [{"user_id": detached_user.pk, "role_id": role_member.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_org_admin_other_org_403(
        self,
        authed_client,
        org_admin_acme,
        org_globex,
        detached_user,
        role_member,
    ):
        resp = authed_client(org_admin_acme).post(
            org_assign_users_url(org_globex.pk),
            {"assignments": [{"user_id": detached_user.pk, "role_id": role_member.pk}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_non_numeric_org_id_404(self, authed_client, superadmin):
        resp = authed_client(superadmin).post(
            "/api/admin/organizations/abc/assign-users/",
            {"assignments": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestAssignUsersSelfAssign:
    """Caller-relationship UX rule: non-superadmin cannot include themselves
    in the batch. Superadmin bypasses."""

    def test_org_admin_includes_self_400_cannot_self_assign(
        self,
        authed_client,
        org_admin_acme,
        org_acme,
        detached_user,
        role_member,
    ):
        resp = authed_client(org_admin_acme).post(
            org_assign_users_url(org_acme.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                    {"user_id": org_admin_acme.pk, "role_id": role_member.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "cannot_self_assign"
        # All-or-nothing: detached_user must NOT have been linked.
        assert not OrganizationUser.objects.filter(
            user=detached_user, org=org_acme
        ).exists()

    def test_superadmin_includes_self_200_bypasses_rule(
        self,
        authed_client,
        superadmin,
        org_globex,
        detached_user,
        role_member,
        role_org_admin,
    ):
        # superadmin is in org_acme but not in org_globex; including self
        # in a batch on org_globex must succeed.
        resp = authed_client(superadmin).post(
            org_assign_users_url(org_globex.pk),
            {
                "assignments": [
                    {"user_id": detached_user.pk, "role_id": role_member.pk},
                    {"user_id": superadmin.pk, "role_id": role_org_admin.pk},
                ]
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["created"]) == 2
