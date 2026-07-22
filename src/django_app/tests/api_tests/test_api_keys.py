"""API key management tests (EST-2956): generator, model, auth,
self-service endpoints, SECRETS-gated management, system key."""

import hashlib
from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import ApiKey, Organization, OrganizationUser, Role
from tables.services.rbac.api_key.generator import (
    KEY_PREFIX,
    PREFIX_LENGTH,
    ApiKeyGenerator,
)
from tables.services.rbac.api_key.principals import (
    PrincipalResolver,
    SystemServicePrincipal,
)
from tables.services.rbac.api_key.system_key_service import SystemKeyService

PROFILE_URL = "/api/profile/"
INTROSPECT_URL = "/api/auth/introspect/"
VALIDATE_URL = "/api/auth/api-key/validate/"
PROFILE_KEYS_URL = "/api/profile/api-keys/"
SSE_TICKET_URL = "/api/auth/sse-ticket/"
ROLES_ADMIN_URL = "/api/admin/roles/"


def profile_key_url(key_id):
    return f"{PROFILE_KEYS_URL}{key_id}/"


def profile_key_revoke_url(key_id):
    return f"{PROFILE_KEYS_URL}{key_id}/revoke/"


class TestApiKeyGenerator:
    def test_generate_returns_prefixed_raw_key(self):
        generated = ApiKeyGenerator.generate()
        assert generated.raw_key.startswith(KEY_PREFIX)
        assert len(generated.raw_key) > 40  # es_ + 43-char token

    def test_generate_prefix_is_first_12_chars(self):
        generated = ApiKeyGenerator.generate()
        assert generated.prefix == generated.raw_key[:PREFIX_LENGTH]
        assert len(generated.prefix) == 12

    def test_generate_hash_is_sha256_of_raw(self):
        generated = ApiKeyGenerator.generate()
        expected = hashlib.sha256(generated.raw_key.encode()).hexdigest()
        assert generated.key_hash == expected

    def test_generate_is_unique_per_call(self):
        a, b = ApiKeyGenerator.generate(), ApiKeyGenerator.generate()
        assert a.raw_key != b.raw_key
        assert a.key_hash != b.key_hash

    def test_hash_key_matches_generate(self):
        generated = ApiKeyGenerator.generate()
        assert ApiKeyGenerator.hash_key(generated.raw_key) == generated.key_hash


@pytest.mark.django_db
class TestApiKeyModel:
    def test_user_key_without_owner_violates_constraint(self, regular_user):
        generated = ApiKeyGenerator.generate()
        with pytest.raises(IntegrityError):
            ApiKey.objects.create(
                name="bad",
                key_type=ApiKey.KeyType.USER,
                prefix=generated.prefix,
                key_hash=generated.key_hash,
                created_by=None,
            )

    def test_system_key_with_owner_violates_constraint(self, regular_user):
        generated = ApiKeyGenerator.generate()
        with pytest.raises(IntegrityError):
            ApiKey.objects.create(
                name="bad",
                key_type=ApiKey.KeyType.SYSTEM,
                prefix=generated.prefix,
                key_hash=generated.key_hash,
                created_by=regular_user,
            )

    def test_system_key_with_expiry_violates_constraint(self):
        generated = ApiKeyGenerator.generate()
        with pytest.raises(IntegrityError):
            ApiKey.objects.create(
                name="bad",
                key_type=ApiKey.KeyType.SYSTEM,
                prefix=generated.prefix,
                key_hash=generated.key_hash,
                expires_at=timezone.now() + timedelta(days=1),
            )

    def test_deleting_user_cascades_keys(self, regular_user, issue_api_key):
        _, key = issue_api_key(user=regular_user)
        regular_user.delete()
        assert not ApiKey.objects.filter(pk=key.pk).exists()

    def test_status_property(self, regular_user, issue_api_key):
        _, active = issue_api_key(user=regular_user)
        _, expired = issue_api_key(
            user=regular_user, expires_at=timezone.now() - timedelta(seconds=1)
        )
        _, revoked = issue_api_key(user=regular_user, revoked_at=timezone.now())
        assert active.status == "active"
        assert expired.status == "expired"
        assert revoked.status == "revoked"


@pytest.mark.django_db
class TestApiKeyAuthentication:
    def test_user_key_authenticates_as_owner(
        self, regular_user, user_api_key, default_org
    ):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )
        resp = client.get(PROFILE_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["email"] == regular_user.email

    def test_revoked_key_401(self, regular_user, issue_api_key):
        raw, _ = issue_api_key(user=regular_user, revoked_at=timezone.now())
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        assert client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_key_401(self, regular_user, issue_api_key):
        raw, _ = issue_api_key(
            user=regular_user, expires_at=timezone.now() - timedelta(seconds=1)
        )
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        assert client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_unknown_key_401(self):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY="es_not-a-real-key")
        assert client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_system_key_is_superadmin_principal(self, env_api_key):
        raw, key = env_api_key
        principal = PrincipalResolver().resolve(key)
        assert isinstance(principal, SystemServicePrincipal)
        assert principal.is_authenticated is True
        assert principal.is_superadmin is True
        assert not hasattr(principal, "email")

    def test_system_key_blocked_on_profile_but_passes_auth(self, env_api_key):
        # Profile needs a user identity; system principal has none → 403
        # (NOT 401 — authentication itself succeeds).
        raw, _ = env_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        assert client.get(PROFILE_URL).status_code == status.HTTP_403_FORBIDDEN

    def test_mark_used_throttled(self, regular_user, user_api_key, default_org):
        raw, key = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )
        client.get(PROFILE_URL)
        key.refresh_from_db()
        first = key.last_used_at
        assert first is not None
        client.get(PROFILE_URL)  # within 60 s window — no write
        key.refresh_from_db()
        assert key.last_used_at == first


@pytest.mark.django_db
class TestSystemKeySeeding:
    def test_seed_creates_system_key(self):
        key = SystemKeyService().seed_from_env("my-secret-value")
        assert key.key_type == ApiKey.KeyType.SYSTEM
        assert key.created_by is None
        assert key.expires_at is None
        assert key.key_hash == ApiKeyGenerator.hash_key("my-secret-value")

    def test_seed_is_idempotent(self):
        service = SystemKeyService()
        first = service.seed_from_env("my-secret-value")
        second = service.seed_from_env("my-secret-value")
        assert first.pk == second.pk
        assert ApiKey.objects.filter(key_type=ApiKey.KeyType.SYSTEM).count() == 1

    def test_seed_rotation_revokes_old_singleton(self):
        service = SystemKeyService()
        old = service.seed_from_env("old-secret")
        new = service.seed_from_env("new-secret")
        old.refresh_from_db()
        assert old.is_revoked
        assert not new.is_revoked
        active = ApiKey.objects.filter(
            key_type=ApiKey.KeyType.SYSTEM, revoked_at__isnull=True
        )
        assert list(active) == [new]

    def test_seed_empty_env_returns_none(self):
        assert SystemKeyService().seed_from_env("") is None
        assert SystemKeyService().seed_from_env(None) is None


@pytest.mark.django_db
class TestInternalEndpointHardening:
    def test_introspect_accepts_system_key(self, env_api_key, superadmin_jwt_tokens):
        raw, _ = env_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.post(
            INTROSPECT_URL,
            data={"token": superadmin_jwt_tokens["access"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["active"] is True

    def test_introspect_rejects_user_key(self, user_api_key):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.post(INTROSPECT_URL, data={"token": "x"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_validate_returns_metadata_without_scopes(self, user_api_key):
        raw, key = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.get(VALIDATE_URL)
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["active"] is True
        assert body["prefix"] == key.prefix
        assert "scopes" not in body


@pytest.mark.django_db
class TestSelfServiceApiKeys:
    def test_create_returns_raw_key_once(self, auth_client):
        resp = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "mcp-laptop"}, format="json"
        )
        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body["api_key"].startswith("es-")
        assert body["name"] == "mcp-laptop"
        assert body["status"] == "active"
        # default 90d expiry applied
        assert body["expires_at"] is not None
        # raw key never appears in the list
        listed = auth_client.get(PROFILE_KEYS_URL).json()
        assert "api_key" not in listed[0]
        assert "key_hash" not in listed[0]

    def test_create_no_expiry_when_null(self, auth_client):
        resp = auth_client.post(
            PROFILE_KEYS_URL,
            data={"name": "forever", "expires_in_days": None},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["expires_at"] is None

    def test_create_invalid_ttl_400(self, auth_client):
        resp = auth_client.post(
            PROFILE_KEYS_URL,
            data={"name": "bad", "expires_in_days": 0},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cap_5_active_keys(self, auth_client, regular_user, issue_api_key):
        for i in range(5):
            issue_api_key(user=regular_user, name=f"k{i}")
        resp = auth_client.post(PROFILE_KEYS_URL, data={"name": "sixth"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "api_key_limit_exceeded"

    def test_revoked_keys_do_not_count_toward_cap(
        self, auth_client, regular_user, issue_api_key
    ):
        for i in range(5):
            issue_api_key(user=regular_user, name=f"k{i}", revoked_at=timezone.now())
        resp = auth_client.post(PROFILE_KEYS_URL, data={"name": "ok"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED

    def test_list_own_keys_only(self, auth_client, superadmin_user, issue_api_key):
        issue_api_key(user=superadmin_user, name="not-mine")
        auth_client.post(PROFILE_KEYS_URL, data={"name": "mine"}, format="json")
        names = [k["name"] for k in auth_client.get(PROFILE_KEYS_URL).json()]
        assert names == ["mine"]

    def test_revoke_own_key(self, auth_client, regular_user, issue_api_key):
        raw, key = issue_api_key(user=regular_user)
        resp = auth_client.post(profile_key_revoke_url(key.pk))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "revoked"
        # revoked key fails auth immediately
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        assert client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_own_key(self, auth_client, regular_user, issue_api_key):
        _, key = issue_api_key(user=regular_user)
        assert (
            auth_client.delete(profile_key_url(key.pk)).status_code
            == status.HTTP_204_NO_CONTENT
        )
        assert not ApiKey.objects.filter(pk=key.pk).exists()

    def test_foreign_key_id_404(self, auth_client, superadmin_user, issue_api_key):
        _, key = issue_api_key(user=superadmin_user)
        assert (
            auth_client.delete(profile_key_url(key.pk)).status_code
            == status.HTTP_404_NOT_FOUND
        )
        assert (
            auth_client.post(profile_key_revoke_url(key.pk)).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_api_key_cannot_manage_keys(self, user_api_key):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.post(PROFILE_KEYS_URL, data={"name": "sneaky"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_default_expiry_is_90_days(self, auth_client):
        resp = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "default-ttl"}, format="json"
        )
        expires_at = datetime.fromisoformat(
            resp.json()["expires_at"].replace("Z", "+00:00")
        )
        delta = expires_at - timezone.now()
        assert timedelta(days=89) < delta <= timedelta(days=90)


@pytest.mark.django_db
class TestApiKeyPermissionParity:
    """A key acts exactly as its owner per X-Organization-Id (MCP flow)."""

    def test_key_with_org_header_hits_org_scoped_endpoint(
        self, regular_user, user_api_key, default_org
    ):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )
        # regular_user is Org Admin of default_org (roles: READ)
        assert client.get(ROLES_ADMIN_URL).status_code == status.HTTP_200_OK

    def test_key_against_non_member_org_403(self, user_api_key, default_org):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id + 999)
        )
        assert (
            client.get("/api/permissions/me/").status_code == status.HTTP_403_FORBIDDEN
        )

    def test_sse_ticket_via_api_key(self, user_api_key):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.post(SSE_TICKET_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert "ticket" in resp.json()


ADMIN_KEYS_URL = "/api/api-keys/"


def admin_key_url(key_id):
    return f"{ADMIN_KEYS_URL}{key_id}/"


def admin_key_revoke_url(key_id):
    return f"{ADMIN_KEYS_URL}{key_id}/revoke/"


@pytest.fixture
def other_org_user(db, issue_api_key):
    """A user + key in a different org — must be invisible to default_org managers."""
    org = Organization.objects.create(name="Other Org")
    role = Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
    user = get_user_model().objects.create_user(
        email="other@example.com", password="OtherStrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    raw, key = issue_api_key(user=user, name="other-org-key")
    return user, org, key


@pytest.mark.django_db
class TestApiKeyManagement:
    """Org Admin (SECRETS CRUD in seed 0183) manages active-org members' keys."""

    def test_list_scoped_to_active_org_members(
        self, auth_client, regular_user, issue_api_key, other_org_user
    ):
        issue_api_key(user=regular_user, name="member-key")
        resp = auth_client.get(ADMIN_KEYS_URL)
        assert resp.status_code == status.HTTP_200_OK
        names = [k["name"] for k in resp.json()]
        assert "member-key" in names
        assert "other-org-key" not in names
        assert resp.json()[0]["owner"]["email"]

    def test_system_key_never_listed(self, auth_client, env_api_key):
        names = [k["name"] for k in auth_client.get(ADMIN_KEYS_URL).json()]
        assert "env-system" not in names

    def test_cross_org_key_revoke_404(self, auth_client, other_org_user):
        _, _, key = other_org_user
        assert (
            auth_client.post(admin_key_revoke_url(key.pk)).status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_revoke_member_key(self, auth_client, regular_user, issue_api_key):
        raw, key = issue_api_key(user=regular_user)
        resp = auth_client.post(admin_key_revoke_url(key.pk))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "revoked"

    def test_delete_member_key(self, auth_client, regular_user, issue_api_key):
        _, key = issue_api_key(user=regular_user)
        assert (
            auth_client.delete(admin_key_url(key.pk)).status_code
            == status.HTTP_204_NO_CONTENT
        )

    def test_status_filter(self, auth_client, regular_user, issue_api_key):
        issue_api_key(user=regular_user, name="live")
        issue_api_key(user=regular_user, name="dead", revoked_at=timezone.now())
        names = [
            k["name"]
            for k in auth_client.get(ADMIN_KEYS_URL, {"status": "revoked"}).json()
        ]
        assert names == ["dead"]

    def test_invalid_status_filter_400(self, auth_client):
        resp = auth_client.get(ADMIN_KEYS_URL, {"status": "bogus"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_without_secrets_read_403(
        self, api_client, default_org, issue_api_key
    ):
        """Built-in Member role has secrets=192 (USE|LIST) — no READ bit."""
        member_role = Role.objects.get(
            name="Member", is_built_in=True, org__isnull=True
        )
        member = get_user_model().objects.create_user(
            email="plain-member@example.com", password="MemberStrongPass123!"
        )
        OrganizationUser.objects.create(user=member, org=default_org, role=member_role)
        access = str(RefreshToken.for_user(member).access_token)
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}",
            HTTP_X_ORGANIZATION_ID=str(default_org.id),
        )
        assert api_client.get(ADMIN_KEYS_URL).status_code == status.HTTP_403_FORBIDDEN

    def test_superadmin_sees_all_orgs_without_header(
        self, superadmin_client, regular_user, issue_api_key, other_org_user
    ):
        issue_api_key(user=regular_user, name="member-key")
        names = [k["name"] for k in superadmin_client.get(ADMIN_KEYS_URL).json()]
        assert "member-key" in names
        assert "other-org-key" in names

    def test_api_key_blocked_on_management(
        self, regular_user, user_api_key, default_org
    ):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )
        assert client.get(ADMIN_KEYS_URL).status_code == status.HTTP_403_FORBIDDEN

    def test_api_key_blocked_on_management_revoke_and_delete(
        self, regular_user, user_api_key, issue_api_key, default_org
    ):
        raw, _ = user_api_key
        _, target = issue_api_key(user=regular_user, name="target")
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )
        assert (
            client.post(admin_key_revoke_url(target.pk)).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            client.delete(admin_key_url(target.pk)).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_system_key_id_404_on_management_mutation(self, auth_client, env_api_key):
        _, system_key = env_api_key
        assert (
            auth_client.post(admin_key_revoke_url(system_key.pk)).status_code
            == status.HTTP_404_NOT_FOUND
        )
        assert (
            auth_client.delete(admin_key_url(system_key.pk)).status_code
            == status.HTTP_404_NOT_FOUND
        )
