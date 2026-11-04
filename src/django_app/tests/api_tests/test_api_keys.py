"""API key tests: generator, model, authentication, self-service
endpoints, and system key."""

from datetime import datetime, timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import ApiKey, OrganizationUser
from rbac.identity.api_keys.generator import (
    KEY_PREFIX,
    PREFIX_LENGTH,
    ApiKeyGenerator,
)
from rbac.identity.api_keys.system_key import SystemKeyService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

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


def test_generated_keys_are_unique_prefixed_and_stored_only_as_a_hash():
    first, second = ApiKeyGenerator.generate(), ApiKeyGenerator.generate()

    assert first.raw_key != second.raw_key
    assert first.raw_key.startswith(KEY_PREFIX)
    # The prefix is what the UI shows; it identifies a key without revealing it.
    assert first.prefix == first.raw_key[:PREFIX_LENGTH] and len(first.prefix) == 12
    assert first.raw_key not in first.key_hash
    assert ApiKeyGenerator.hash_key(first.raw_key) == first.key_hash != second.key_hash


@pytest.mark.django_db
class TestApiKeyModel:
    @pytest.mark.parametrize(
        ("key_type", "owned", "expires"),
        [(ApiKey.KeyType.USER, False, False), (ApiKey.KeyType.SYSTEM, True, False), (ApiKey.KeyType.SYSTEM, False, True)],
        ids=["user-key-without-owner", "system-key-with-owner", "system-key-with-expiry"],
    )
    def test_key_ownership_and_expiry_are_enforced_by_the_database(self, regular_user, key_type, owned, expires):
        generated = ApiKeyGenerator.generate()
        with pytest.raises(IntegrityError):
            ApiKey.objects.create(
                name="bad",
                key_type=key_type,
                prefix=generated.prefix,
                key_hash=generated.key_hash,
                created_by=regular_user if owned else None,
                expires_at=timezone.now() + timedelta(days=1) if expires else None,
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

    @pytest.mark.parametrize(
        "spoil",
        [
            lambda issue, user: issue(user=user, revoked_at=timezone.now())[0],
            lambda issue, user: issue(user=user, expires_at=timezone.now() - timedelta(seconds=1))[0],
            lambda issue, user: "es_not-a-real-key",
        ],
        ids=["revoked", "expired", "unknown"],
    )
    def test_unusable_key_is_401(self, regular_user, issue_api_key, spoil):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=spoil(issue_api_key, regular_user))
        assert client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

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

    def test_validate_names_the_org_of_a_user_key(self, user_api_key):
        raw, key = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)

        body = client.get(VALIDATE_URL).json()

        assert (body["owner_user_id"], body["org_id"]) == (key.created_by_id, key.org_id)
        assert body["org_id"] is not None

    def test_validate_gives_a_system_key_no_org(self, env_api_key):
        raw, _ = env_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)

        body = client.get(VALIDATE_URL).json()

        assert (body["owner_user_id"], body["org_id"]) == (None, None)


@pytest.mark.django_db
class TestSelfServiceApiKeys:
    def test_create_returns_the_raw_key_once_with_a_90_day_default_expiry(self, auth_client, default_org):
        resp = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "mcp-laptop", "org_id": default_org.id}, format="json"
        )

        assert resp.status_code == status.HTTP_201_CREATED
        body = resp.json()
        assert body["api_key"].startswith("es-")
        assert (body["name"], body["status"], body["org_id"]) == ("mcp-laptop", "active", default_org.id)
        expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert timedelta(days=89) < expires_at - timezone.now() <= timedelta(days=90)
        (listed,) = auth_client.get(PROFILE_KEYS_URL).json()
        assert "api_key" not in listed and "key_hash" not in listed

    @pytest.mark.parametrize(("expires_in_days", "expected_status"), [(None, 201), (0, 400)])
    def test_create_expiry_choice(self, auth_client, default_org, expires_in_days, expected_status):
        resp = auth_client.post(
            PROFILE_KEYS_URL,
            data={"name": "k", "org_id": default_org.id, "expires_in_days": expires_in_days},
            format="json",
        )

        assert resp.status_code == expected_status
        if expected_status == 201:
            assert resp.json()["expires_at"] is None

    @pytest.mark.parametrize(("revoked", "expected_status"), [(False, 400), (True, 201)], ids=["active", "revoked"])
    def test_at_most_five_active_keys(
        self, auth_client, regular_user, default_org, issue_api_key, revoked, expected_status
    ):
        for index in range(5):
            issue_api_key(user=regular_user, name=f"k{index}", revoked_at=timezone.now() if revoked else None)

        resp = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "sixth", "org_id": default_org.id}, format="json"
        )

        assert resp.status_code == expected_status
        if expected_status == 400:
            assert resp.json()["code"] == "api_key_limit_exceeded"

    def test_list_own_keys_only(self, auth_client, superadmin_user, default_org, issue_api_key):
        issue_api_key(user=superadmin_user, name="not-mine")
        auth_client.post(PROFILE_KEYS_URL, data={"name": "mine", "org_id": default_org.id}, format="json")
        names = [k["name"] for k in auth_client.get(PROFILE_KEYS_URL).json()]
        assert names == ["mine"]

    @pytest.mark.parametrize(
        "org_id, reason",
        [
            (None, "Organization is required."),
            ("1", "Must be a positive integer."),
            (0, "Must be a positive integer."),
            (True, "Must be a positive integer."),
        ],
        ids=["missing", "string", "zero", "bool"],
    )
    def test_create_key_requires_org_id(self, auth_client, org_id, reason):
        data = {"name": "k"} if org_id is None else {"name": "k", "org_id": org_id}

        resp = auth_client.post(PROFILE_KEYS_URL, data=data, format="json")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == "invalid"
        assert [(error["field"], error["reason"]) for error in body["errors"]] == [
            ("org_id", reason)
        ]

    def test_create_key_in_org_user_is_not_member_of(self, auth_client, regular_user, acme):
        resp = auth_client.post(PROFILE_KEYS_URL, data={"name": "k", "org_id": acme.id}, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()["code"] == "org_membership_required"
        assert not ApiKey.objects.filter(created_by=regular_user).exists()

    def test_member_cannot_create_key_in_inactive_org(self, auth_client, regular_user, default_org):
        default_org.is_active = False
        default_org.save(update_fields=["is_active"])

        resp = auth_client.post(PROFILE_KEYS_URL, data={"name": "k", "org_id": default_org.id}, format="json")

        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()["code"] == "org_membership_required"
        assert not ApiKey.objects.filter(created_by=regular_user).exists()

    @pytest.mark.parametrize(("org_is_active", "expected_status"), [(True, 201), (False, 403)], ids=["active", "inactive"])
    def test_superadmin_creates_key_in_any_active_org(
        self, superadmin_client, superadmin_user, acme, org_is_active, expected_status
    ):
        acme.is_active = org_is_active
        acme.save(update_fields=["is_active"])

        resp = superadmin_client.post(PROFILE_KEYS_URL, data={"name": "k", "org_id": acme.id}, format="json")

        assert resp.status_code == expected_status
        assert list(ApiKey.objects.filter(created_by=superadmin_user).values_list("org_id", flat=True)) == (
            [acme.id] if org_is_active else []
        )

    def test_superadmin_create_in_missing_org(self, superadmin_client, acme):
        missing_org_id = acme.id + 1000

        resp = superadmin_client.post(PROFILE_KEYS_URL, data={"name": "k", "org_id": missing_org_id}, format="json")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["code"] == "organization_not_found"

    def test_cap_is_five_per_org(self, auth_client, regular_user, default_org, acme, role_member, issue_api_key):
        OrganizationUser.objects.create(user=regular_user, org=acme, role=role_member)
        for index in range(5):
            issue_api_key(user=regular_user, org=default_org, name=f"k{index}")

        sixth_in_same_org = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "sixth", "org_id": default_org.id}, format="json"
        )
        first_in_other_org = auth_client.post(
            PROFILE_KEYS_URL, data={"name": "acme", "org_id": acme.id}, format="json"
        )

        assert sixth_in_same_org.status_code == status.HTTP_400_BAD_REQUEST
        assert sixth_in_same_org.json()["code"] == "api_key_limit_exceeded"
        assert first_in_other_org.status_code == status.HTTP_201_CREATED

    def test_list_shows_org_of_each_key(
        self, auth_client, regular_user, default_org, acme, role_member, issue_api_key
    ):
        OrganizationUser.objects.create(user=regular_user, org=acme, role=role_member)
        issue_api_key(user=regular_user, org=default_org, name="default-key")
        issue_api_key(user=regular_user, org=acme, name="acme-key")

        listed = auth_client.get(PROFILE_KEYS_URL).json()

        assert {(key["name"], key["org_id"], key["org_name"]) for key in listed} == {
            ("default-key", default_org.id, "Default Organization"),
            ("acme-key", acme.id, "Acme-xorg"),
        }

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

@pytest.mark.django_db
class TestApiKeyPermissionParity:
    """A key acts exactly as its owner, in the key's org (MCP flow)."""

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

    def test_key_ignores_header_naming_another_org(self, user_api_key, default_org):
        raw, key = user_api_key
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(default_org.id + 999)
        )
        response = client.get("/api/permissions/me/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["org_id"] == key.org_id

    def test_sse_ticket_via_api_key(self, user_api_key):
        raw, _ = user_api_key
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        resp = client.post(SSE_TICKET_URL)
        assert resp.status_code == status.HTTP_200_OK
        assert "ticket" in resp.json()


@pytest.mark.django_db
def test_key_of_deactivated_owner_is_rejected(api_client, regular_user, issue_api_key):
    raw, key = issue_api_key(user=regular_user, name="soon-dead")
    regular_user.is_active = False
    regular_user.save(update_fields=["is_active"])

    api_client.credentials(HTTP_X_API_KEY=raw)
    resp = api_client.get(PROFILE_URL)

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "inactive" in resp.json()["message"].lower()
    key.refresh_from_db()
    assert key.last_used_at is None


@pytest.mark.django_db
def test_key_works_again_once_the_owner_is_reactivated(
    api_client, regular_user, issue_api_key
):
    raw, _ = issue_api_key(user=regular_user, name="revived")
    api_client.credentials(HTTP_X_API_KEY=raw)

    regular_user.is_active = False
    regular_user.save(update_fields=["is_active"])
    assert api_client.get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED

    regular_user.is_active = True
    regular_user.save(update_fields=["is_active"])
    assert api_client.get(PROFILE_URL).status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_system_key_is_unaffected_by_the_owner_check(api_client, env_api_key):
    raw, _ = env_api_key

    api_client.credentials(HTTP_X_API_KEY=raw)
    resp = api_client.get(VALIDATE_URL)

    assert resp.status_code == status.HTTP_200_OK
