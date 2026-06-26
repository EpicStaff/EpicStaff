"""
Story 6 — User profile endpoint tests.

Test scaffolding mirrors tests/api_tests/test_rbac_user_management.py:
fixtures are defined locally (not in conftest.py); `authed_client` uses
`force_authenticate` for cheap per-test logins; env-seeded API keys are
created via the ApiKey model directly.
"""

import io
import pathlib
import shutil

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import (
    ApiKey,
    Organization,
    OrganizationUser,
    Role,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- shared fixtures ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Profile Acme")


@pytest.fixture
def member_acme(django_user_model, org_acme, role_member):
    user = django_user_model.objects.create_user(
        email="profile-member@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_member)
    return user


@pytest.fixture
def orphan_user(django_user_model):
    """A user with no organization memberships at all."""
    return django_user_model.objects.create_user(
        email="orphan@x.test", password="StrongPass123!"
    )


@pytest.fixture
def member_with_two_orgs(django_user_model, role_member):
    user = django_user_model.objects.create_user(
        email="dual@x.test", password="StrongPass123!"
    )
    org_a = Organization.objects.create(name="ProfileTestOrgA")
    org_b = Organization.objects.create(name="ProfileTestOrgB")
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    OrganizationUser.objects.create(user=user, org=org_b, role=role_member)
    return user, org_a, org_b


@pytest.fixture
def deactivate_org(db):
    def _do(org):
        org.is_active = False
        org.save(update_fields=["is_active"])

    return _do


@pytest.fixture
def authed_client():
    def _build(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _build


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def tmp_media_root(settings, tmp_path):
    """Point MEDIA_ROOT at the project's tmp dir for the test, and wipe the
    avatars/ subtree on exit. The project's tmp_path fixture in
    tests/conftest.py is a fixed path that does NOT auto-clean, so without
    this finalizer test artifacts accumulate."""
    settings.MEDIA_ROOT = str(tmp_path)
    yield tmp_path
    avatars_dir = pathlib.Path(tmp_path) / "avatars"
    if avatars_dir.exists():
        shutil.rmtree(avatars_dir, ignore_errors=True)


@pytest.fixture
def env_api_key_credentials(db):
    """X-Api-Key header value for an env-seeded ApiKey (created_by=None)."""
    raw = ApiKey.generate_raw_key()
    key = ApiKey(name="env-seeded-test", created_by=None)
    key.set_key(raw)
    key.save()
    return raw


# ---- helpers ----


def _make_image_bytes(format_name: str, size=(64, 64), color=(200, 100, 50)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


def _make_text_bytes() -> bytes:
    return b"this is not a real image, just some text\n"


# ===========================================================================
# TestProfileGet
# ===========================================================================


@pytest.mark.django_db
class TestProfileGet:
    URL = "/api/profile/"

    def test_happy_path_returns_user_with_memberships(
        self, authed_client, member_acme, org_acme, role_member
    ):
        resp = authed_client(member_acme).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["id"] == member_acme.id
        assert body["email"] == member_acme.email
        assert body["is_superadmin"] is False
        assert body["is_active"] is True
        assert isinstance(body["memberships"], list)
        assert any(
            m["organization"]["id"] == org_acme.id
            and m["role"]["name"] == role_member.name
            for m in body["memberships"]
        )

    def test_returns_403_for_env_api_key(self, api_client, env_api_key_credentials):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_401_when_unauthenticated(self, api_client):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_inactive_org_membership_filtered_out(
        self, authed_client, member_with_two_orgs, deactivate_org
    ):
        user, active_org, inactive_org = member_with_two_orgs
        deactivate_org(inactive_org)

        resp = authed_client(user).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        org_ids = [m["organization"]["id"] for m in resp.json()["memberships"]]
        assert active_org.id in org_ids
        assert inactive_org.id not in org_ids

    def test_memberships_sorted_by_joined_at_ascending(
        self, authed_client, member_with_two_orgs
    ):
        user, _, _ = member_with_two_orgs
        resp = authed_client(user).get(self.URL)
        joined_ats = [m["joined_at"] for m in resp.json()["memberships"]]
        assert joined_ats == sorted(joined_ats)

    def test_zero_memberships_user(self, authed_client, orphan_user):
        resp = authed_client(orphan_user).get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["memberships"] == []

    def test_no_avatar_returns_null_url(self, authed_client, member_acme):
        member_acme.avatar = None
        member_acme.save(update_fields=["avatar"])
        resp = authed_client(member_acme).get(self.URL)
        assert resp.json()["avatar_url"] is None

    def test_with_avatar_returns_absolute_url(
        self, authed_client, member_acme, tmp_media_root
    ):
        member_acme.avatar.save(
            "seed.png",
            ContentFile(_make_image_bytes("PNG")),
            save=True,
        )
        resp = authed_client(member_acme).get(self.URL)
        url = resp.json()["avatar_url"]
        assert url is not None
        assert url.startswith("http")
        assert "/media/avatars/" in url


# ===========================================================================
# TestProfilePatch
# ===========================================================================


@pytest.mark.django_db
class TestProfilePatch:
    URL = "/api/profile/"

    def test_set_display_name(self, authed_client, member_acme):
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": "Alice Doe"}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["display_name"] == "Alice Doe"
        member_acme.refresh_from_db()
        assert member_acme.display_name == "Alice Doe"

    def test_trim_whitespace(self, authed_client, member_acme):
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": "  Padded  "}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["display_name"] == "Padded"

    def test_clear_with_null(self, authed_client, member_acme):
        member_acme.display_name = "Set"
        member_acme.save(update_fields=["display_name"])
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": None}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["display_name"] is None

    def test_empty_body_noops(self, authed_client, member_acme):
        member_acme.display_name = "Keep"
        member_acme.save(update_fields=["display_name"])
        resp = authed_client(member_acme).patch(self.URL, {}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["display_name"] == "Keep"

    def test_empty_string_rejected(self, authed_client, member_acme):
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": ""}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == "invalid"
        assert any(e["field"] == "display_name" for e in body["errors"])

    def test_non_string_rejected(self, authed_client, member_acme):
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": 42}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_too_long_rejected(self, authed_client, member_acme):
        resp = authed_client(member_acme).patch(
            self.URL, {"display_name": "x" * 256}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_keys_silently_ignored(self, authed_client, member_acme):
        before = member_acme.is_superadmin
        resp = authed_client(member_acme).patch(
            self.URL,
            {
                "display_name": "Updated",
                "is_superadmin": True,
                "email": "evil@x.test",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        member_acme.refresh_from_db()
        assert member_acme.is_superadmin is before
        assert member_acme.email != "evil@x.test"

    def test_returns_403_for_env_api_key(self, api_client, env_api_key_credentials):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        resp = api_client.patch(self.URL, {"display_name": "X"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# TestProfileAvatarUpload
# ===========================================================================


@pytest.mark.django_db
class TestProfileAvatarUpload:
    URL = "/api/profile/avatar/"

    def test_happy_jpeg(self, authed_client, member_acme, tmp_media_root):
        upload = SimpleUploadedFile(
            "a.jpg", _make_image_bytes("JPEG"), content_type="image/jpeg"
        )
        resp = authed_client(member_acme).post(
            self.URL, {"avatar": upload}, format="multipart"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["avatar_url"] is not None

    def test_reject_gif(self, authed_client, member_acme, tmp_media_root):
        upload = SimpleUploadedFile(
            "a.gif", _make_image_bytes("GIF"), content_type="image/gif"
        )
        resp = authed_client(member_acme).post(
            self.URL, {"avatar": upload}, format="multipart"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid_avatar"

    def test_reject_text_disguised_as_png(
        self, authed_client, member_acme, tmp_media_root
    ):
        upload = SimpleUploadedFile(
            "evil.png", _make_text_bytes(), content_type="image/png"
        )
        resp = authed_client(member_acme).post(
            self.URL, {"avatar": upload}, format="multipart"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid_avatar"

    def test_reject_oversize(
        self, authed_client, member_acme, settings, tmp_media_root
    ):
        settings.AVATAR_MAX_BYTES = 1024  # 1 KiB cap for this test
        big = _make_image_bytes("PNG", size=(512, 512))
        upload = SimpleUploadedFile("big.png", big, content_type="image/png")
        resp = authed_client(member_acme).post(
            self.URL, {"avatar": upload}, format="multipart"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "avatar_too_large"

    def test_missing_field_returns_400(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(self.URL, {}, format="multipart")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_403_for_env_api_key(
        self, api_client, env_api_key_credentials, tmp_media_root
    ):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        upload = SimpleUploadedFile(
            "a.png", _make_image_bytes("PNG"), content_type="image/png"
        )
        resp = api_client.post(self.URL, {"avatar": upload}, format="multipart")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# TestProfileAvatarDelete
# ===========================================================================


@pytest.mark.django_db
class TestProfileAvatarDelete:
    URL = "/api/profile/avatar/"

    @pytest.mark.usefixtures("tmp_media_root")
    def test_happy_returns_204_and_clears_db_pointer(self, authed_client, member_acme):
        # Seed an avatar so DELETE has something to clear. tmp_media_root
        # is consumed for its side effect (MEDIA_ROOT override + cleanup).
        member_acme.avatar.save(
            "x.png", ContentFile(_make_image_bytes("PNG")), save=True
        )
        resp = authed_client(member_acme).delete(self.URL)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        # DB pointer is cleared. Disk-file deletion is performed by Django's
        # transaction.on_commit hook — well-tested framework behavior, not
        # asserted here.
        member_acme.refresh_from_db()
        assert not member_acme.avatar

    def test_returns_403_for_env_api_key(self, api_client, env_api_key_credentials):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        resp = api_client.delete(self.URL)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# TestPasswordChangeRequest
# ===========================================================================


@pytest.mark.django_db
class TestPasswordChangeRequest:
    URL = "/api/profile/password-change/request/"

    def test_happy_returns_ticket(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            self.URL, {"current_password": "StrongPass123!"}, format="json"
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert isinstance(body["ticket"], str) and len(body["ticket"]) >= 32
        assert isinstance(body["expires_in"], int) and body["expires_in"] > 0

    def test_wrong_password_returns_400(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            self.URL, {"current_password": "WrongOne!"}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid_current_password"

    def test_missing_field_returns_400(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(self.URL, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid"

    def test_returns_403_for_env_api_key(self, api_client, env_api_key_credentials):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        resp = api_client.post(self.URL, {"current_password": "x"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_throttle_kicks_in(self, authed_client, member_acme):
        # LoginThrottle defaults to 5/min; the 6th attempt must 429.
        # `cache` imported at the top of this file; clearing wipes any
        # throttle bucket left over from other tests.
        cache.clear()
        try:
            client = authed_client(member_acme)
            for _ in range(5):
                client.post(
                    self.URL,
                    {"current_password": "Bad!"},
                    format="json",
                )
            resp = client.post(self.URL, {"current_password": "Bad!"}, format="json")
            assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            assert "Retry-After" in resp.headers
        finally:
            cache.clear()


# ===========================================================================
# TestPasswordChangeConfirm
# ===========================================================================


@pytest.mark.django_db
class TestPasswordChangeConfirm:
    REQUEST_URL = "/api/profile/password-change/request/"
    CONFIRM_URL = "/api/profile/password-change/confirm/"

    def _issue_ticket(self, client, password):
        resp = client.post(
            self.REQUEST_URL,
            {"current_password": password},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        return resp.json()["ticket"]

    def test_happy_returns_fresh_pair_and_logs_in_target(
        self, authed_client, member_acme
    ):
        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        resp = client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "BrandNewPass456!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert "access" in body and "refresh" in body
        # New pair works: hit /api/profile/ with the access token.
        fresh = APIClient()
        fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        assert fresh.get("/api/profile/").status_code == status.HTTP_200_OK

    def test_password_actually_changed(self, authed_client, member_acme):
        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "BrandNewPass456!"},
            format="json",
        )
        member_acme.refresh_from_db()
        assert member_acme.check_password("BrandNewPass456!")
        assert not member_acme.check_password("StrongPass123!")

    def test_old_refresh_blacklisted(self, authed_client, member_acme):
        # simplejwt's BlacklistMixin auto-creates OutstandingToken rows on
        # RefreshToken.for_user when the token_blacklist app is installed
        # (it is — see settings.py). Mint one explicitly so the pre-state
        # is unambiguous.
        RefreshToken.for_user(member_acme)
        pre_outstanding = OutstandingToken.objects.filter(user=member_acme).count()
        assert pre_outstanding >= 1
        pre_blacklisted = BlacklistedToken.objects.filter(
            token__user=member_acme
        ).count()

        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "BrandNewPass456!"},
            format="json",
        )

        post_blacklisted = BlacklistedToken.objects.filter(
            token__user=member_acme
        ).count()
        assert post_blacklisted > pre_blacklisted

    def test_ticket_is_single_use(self, authed_client, member_acme):
        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        first = client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "BrandNewPass456!"},
            format="json",
        )
        assert first.status_code == status.HTTP_200_OK
        second = client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "AnotherOne789!"},
            format="json",
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert second.json()["code"] == "invalid_password_change_ticket"

    def test_unknown_ticket_returns_400(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            self.CONFIRM_URL,
            {"ticket": "totally-bogus", "new_password": "BrandNewPass456!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid_password_change_ticket"

    def test_cross_user_ticket_rejected(self, authed_client, member_acme, orphan_user):
        """Alice issues a ticket; Bob (logged in as himself) tries to
        consume it. Must fail with the generic ticket error and leave
        Alice's password untouched."""
        alice_client = authed_client(member_acme)
        ticket = self._issue_ticket(alice_client, "StrongPass123!")

        bob_client = authed_client(orphan_user)
        resp = bob_client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "EvilTakeover123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "invalid_password_change_ticket"
        member_acme.refresh_from_db()
        assert member_acme.check_password("StrongPass123!")
        assert not member_acme.check_password("EvilTakeover123!")

    def test_weak_new_password_returns_400(self, authed_client, member_acme):
        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        resp = client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "123"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == "invalid"
        assert any(e["field"] == "new_password" for e in body["errors"])

    def test_new_password_redacted_in_error_body(self, authed_client, member_acme):
        client = authed_client(member_acme)
        ticket = self._issue_ticket(client, "StrongPass123!")
        resp = client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": "123"},
            format="json",
        )
        for e in resp.json()["errors"]:
            if e["field"] == "new_password":
                assert e["value"] == "***"

    def test_returns_403_for_env_api_key(self, api_client, env_api_key_credentials):
        api_client.credentials(HTTP_X_API_KEY=env_api_key_credentials)
        resp = api_client.post(
            self.CONFIRM_URL,
            {"ticket": "x", "new_password": "y"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# TestRemovedEndpoints — sanity guard against re-registration
# ===========================================================================


@pytest.mark.django_db
class TestRemovedEndpoints:
    """Catches accidental re-registration of the two endpoints deleted
    in this story."""

    def test_auth_me_is_404(self, authed_client, member_acme):
        resp = authed_client(member_acme).get("/api/auth/me/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_auth_password_change_is_404(self, authed_client, member_acme):
        resp = authed_client(member_acme).post(
            "/api/auth/password-change/",
            {"current_password": "x", "new_password": "y"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---- Active-org extension ----


@pytest.mark.django_db
def test_profile_no_header_returns_null_active_org(auth_client, regular_user):
    response = auth_client.get("/api/profile/")
    assert response.status_code == 200
    body = response.json()
    assert body["active_organization_id"] is None
    assert body["active_permissions"] is None


@pytest.mark.django_db
def test_profile_valid_header_returns_active_permissions(
    auth_client, regular_user, default_org
):
    response = auth_client.get(
        "/api/profile/", HTTP_X_ORGANIZATION_ID=str(default_org.id)
    )
    body = response.json()
    assert body["active_organization_id"] == default_org.id
    # regular_user is Org Admin (conftest) — should have export on flows.
    assert body["active_permissions"]["role"]["name"] == "Org Admin"
    assert "export" in body["active_permissions"]["permissions"]["flows"]


@pytest.mark.django_db
def test_profile_invalid_header_soft_fails(auth_client, regular_user, db):
    from tables.models.rbac_models import Organization

    other = Organization.objects.create(name="Other Inc (profile tests)")
    response = auth_client.get("/api/profile/", HTTP_X_ORGANIZATION_ID=str(other.id))
    # NOT 403 — profile is the FE boot endpoint.
    assert response.status_code == 200
    body = response.json()
    assert body["active_organization_id"] is None
    assert body["active_permissions"] is None


@pytest.mark.django_db
def test_profile_superadmin_with_any_org(
    superadmin_client, superadmin_user, default_org
):
    response = superadmin_client.get(
        "/api/profile/", HTTP_X_ORGANIZATION_ID=str(default_org.id)
    )
    body = response.json()
    assert body["active_organization_id"] == default_org.id
    assert body["active_permissions"]["is_superadmin"] is True
    assert body["active_permissions"]["permissions"] == "*"
