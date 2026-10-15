"""/api/profile/: the signed-in user's own profile, avatar and password change."""

import io
import json
from unittest.mock import ANY

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.refresh_cookie import REFRESH_COOKIE_NAME
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.signals import profile_updated

PROFILE_URL = "/api/profile/"
AVATAR_URL = "/api/profile/avatar/"
REQUEST_URL = "/api/profile/password-change/request/"
CONFIRM_URL = "/api/profile/password-change/confirm/"


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Profile Acme")


@pytest.fixture
def member_acme(django_user_model, org_acme, role_member):
    user = django_user_model.objects.create_user(email="profile-member@x.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_member)
    return user


@pytest.fixture
def orphan_user(django_user_model):
    """A user with no organization memberships at all."""
    return django_user_model.objects.create_user(email="orphan@x.test", password="StrongPass123!")


@pytest.fixture
def tmp_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _image(format_name: str, size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, format=format_name)
    return buffer.getvalue()


def _png_upload(name="a.png", content=None):
    return SimpleUploadedFile(name, content if content is not None else _image("PNG"), content_type="image/png")


# ---- Who may call it ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "url", "body", "format_name"),
    [
        ("get", PROFILE_URL, None, None),
        ("patch", PROFILE_URL, {"display_name": "X"}, "json"),
        ("post", AVATAR_URL, "avatar", "multipart"),
        ("delete", AVATAR_URL, None, None),
        ("post", REQUEST_URL, {"current_password": "x"}, "json"),
        ("post", CONFIRM_URL, {"ticket": "x", "new_password": "y"}, "json"),
    ],
    ids=["get", "patch", "upload-avatar", "delete-avatar", "password-change-request", "password-change-confirm"],
)
def test_an_env_api_key_has_no_profile(issue_api_key, tmp_media_root, method, url, body, format_name):
    """An env-seeded key belongs to no user, so there is no profile to read or change."""
    raw, _ = issue_api_key(user=None)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)
    data = {"avatar": _png_upload()} if body == "avatar" else body

    response = getattr(client, method)(url, data, format=format_name) if data else getattr(client, method)(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_profile_needs_authentication():
    assert APIClient().get(PROFILE_URL).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("url", ["/api/auth/me/", "/api/auth/password-change/"])
def test_the_removed_auth_endpoints_stay_removed(member_acme, url, method):
    assert getattr(client_for(member_acme), method)(url).status_code == status.HTTP_404_NOT_FOUND


# ---- Reading ----


@pytest.mark.django_db
def test_profile_lists_the_users_active_memberships_oldest_first(member_acme, org_acme, role_member):
    newer = Organization.objects.create(name="ProfileTestOrgB")
    inactive = Organization.objects.create(name="ProfileTestOrgC")
    OrganizationUser.objects.create(user=member_acme, org=newer, role=role_member)
    OrganizationUser.objects.create(user=member_acme, org=inactive, role=role_member)
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    Organization.objects.create(name="Someone Elses Org")

    body = client_for(member_acme).get(PROFILE_URL).json()

    assert (body["id"], body["email"], body["is_superadmin"], body["is_active"]) == (
        member_acme.id, member_acme.email, False, True,
    )
    assert [m["organization"]["id"] for m in body["memberships"]] == [org_acme.id, newer.id]
    assert {m["role"]["name"] for m in body["memberships"]} == {role_member.name}
    joined = [m["joined_at"] for m in body["memberships"]]
    assert joined == sorted(joined)


@pytest.mark.django_db
def test_a_user_without_memberships_has_an_empty_list(orphan_user):
    assert client_for(orphan_user).get(PROFILE_URL).json()["memberships"] == []


@pytest.mark.django_db
def test_a_superadmin_is_shown_every_active_org_as_superadmin(superadmin_client):
    org = Organization.objects.create(name="Shape Co")
    Organization.objects.create(name="Inactive Co", is_active=False)

    memberships = superadmin_client.get(PROFILE_URL).json()["memberships"]

    active_ids = set(Organization.objects.filter(is_active=True).values_list("id", flat=True))
    assert {m["organization"]["id"] for m in memberships} == active_ids
    entry = next(m for m in memberships if m["organization"]["id"] == org.id)
    assert entry == {
        **entry,
        "organization": {"id": org.id, "name": "Shape Co", "is_active": True},
        "id": None,
        "joined_at": None,
    }
    assert {m["role"]["name"] for m in memberships} == {BuiltInRole.SUPERADMIN}


@pytest.mark.django_db
@pytest.mark.parametrize("with_avatar", [False, True])
def test_avatar_url_is_absolute_or_null(member_acme, tmp_media_root, with_avatar):
    if with_avatar:
        member_acme.avatar.save("seed.png", ContentFile(_image("PNG")), save=True)

    url = client_for(member_acme).get(PROFILE_URL).json()["avatar_url"]

    if with_avatar:
        assert url.startswith("http") and "/media/avatars/" in url
    else:
        assert url is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "header_org", "expected"),
    [
        ("member", None, None),
        ("member", "default", {"role": "Org Admin"}),
        # Not a member: the profile is the frontend's boot call, so it soft-fails instead of 403.
        ("member", "other", None),
        ("superadmin", "default", {"is_superadmin": True}),
    ],
    ids=["no-header", "member-org", "foreign-org", "superadmin"],
)
def test_profile_reports_the_active_orgs_permissions(
    api_client, jwt_tokens, superadmin_jwt_tokens, regular_user, default_org, caller, header_org, expected
):
    tokens = jwt_tokens if caller == "member" else superadmin_jwt_tokens
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    headers = {}
    if header_org == "default":
        headers["HTTP_X_ORGANIZATION_ID"] = str(default_org.id)
    elif header_org == "other":
        headers["HTTP_X_ORGANIZATION_ID"] = str(Organization.objects.create(name="Other Inc").id)

    response = api_client.get(PROFILE_URL, **headers)

    assert response.status_code == 200
    body = response.json()
    if expected is None:
        assert (body["active_organization_id"], body["active_permissions"]) == (None, None)
    elif caller == "superadmin":
        assert body["active_organization_id"] == default_org.id
        assert body["active_permissions"]["is_superadmin"] is True
        assert body["active_permissions"]["permissions"] == "*"
    else:
        assert body["active_organization_id"] == default_org.id
        assert body["active_permissions"]["role"]["name"] == "Org Admin"
        assert "export" in body["active_permissions"]["permissions"]["flows"]


# ---- Editing ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"display_name": "Alice Doe"}, "Alice Doe"),
        ({"display_name": "  Padded  "}, "Padded"),
        ({"display_name": None}, None),
        ({}, "Keep"),
        # Only display_name is editable here; anything else is ignored.
        ({"display_name": "Updated", "is_superadmin": True, "email": "evil@x.test"}, "Updated"),
    ],
    ids=["set", "trimmed", "cleared", "empty-body", "other-fields-ignored"],
)
def test_patch_changes_only_the_display_name(member_acme, body, expected):
    member_acme.display_name = "Keep"
    member_acme.save(update_fields=["display_name"])

    response = client_for(member_acme).patch(PROFILE_URL, body, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["display_name"] == expected
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.email, member_acme.is_superadmin) == (
        expected, "profile-member@x.com", False,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("display_name", ["", 42, "x" * 256], ids=["empty", "not-a-string", "too-long"])
def test_patch_rejects_an_invalid_display_name(member_acme, display_name):
    response = client_for(member_acme).patch(PROFILE_URL, {"display_name": display_name}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert any(error["field"] == "display_name" for error in response.json()["errors"])


@pytest.mark.django_db
def test_shortcut_overrides_default_to_an_empty_map(member_acme):
    response = client_for(member_acme).get(PROFILE_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["shortcut_overrides"] == {}


@pytest.mark.django_db
def test_patch_replaces_the_whole_shortcut_map(member_acme):
    member_acme.shortcut_overrides = {"node.agent": "Shift+KeyA", "node.task": "Shift+KeyT"}
    member_acme.save(update_fields=["shortcut_overrides"])

    response = client_for(member_acme).patch(
        PROFILE_URL, {"shortcut_overrides": {"node.agent": "Alt+KeyG"}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["shortcut_overrides"] == {"node.agent": "Alt+KeyG"}
    member_acme.refresh_from_db()
    assert member_acme.shortcut_overrides == {"node.agent": "Alt+KeyG"}


@pytest.mark.django_db
def test_patch_without_shortcut_overrides_keeps_them(member_acme):
    member_acme.shortcut_overrides = {"node.agent": "Alt+KeyG"}
    member_acme.save(update_fields=["shortcut_overrides"])

    response = client_for(member_acme).patch(PROFILE_URL, {"display_name": "Renamed"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["shortcut_overrides"] == {"node.agent": "Alt+KeyG"}
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.shortcut_overrides) == ("Renamed", {"node.agent": "Alt+KeyG"})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"anything.the.frontend.wants": "Shift+KeyQ"},
        {"x" * 64: "Shift+KeyA"},
        {"node.agent": "x" * 64},
        {f"action.{index}": "Shift+KeyA" for index in range(100)},
    ],
    ids=["empty", "unknown-action-id", "key-at-limit", "chord-at-limit", "entries-at-limit"],
)
def test_patch_accepts_shortcut_overrides_up_to_the_limits(member_acme, payload):
    response = client_for(member_acme).patch(PROFILE_URL, {"shortcut_overrides": payload}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["shortcut_overrides"] == payload
    member_acme.refresh_from_db()
    assert member_acme.shortcut_overrides == payload


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "Shift+KeyA",
        {"node.agent": 1},
        {"node.agent": None},
        {"node.agent": ""},
        {"": "Shift+KeyA"},
        {"x" * 65: "Shift+KeyA"},
        {"node.agent": "x" * 65},
        {f"action.{index}": "Shift+KeyA" for index in range(101)},
        {"node.agent": "\u0000"},
        {"node.\u0000": "Shift+KeyA"},
        {"node.agent": "\ud800"},
        {"node.agent": "Shift+КейА"},
        {"node.agent": "Shift+\tKeyA"},
    ],
    ids=[
        "null", "list", "string", "non-string-chord", "null-chord", "empty-chord", "empty-key",
        "key-over-limit", "chord-over-limit", "entries-over-limit",
        "nul-chord", "nul-key", "lone-surrogate-chord", "non-ascii-chord", "control-character-chord",
    ],
)
def test_patch_rejects_a_malformed_shortcut_map(member_acme, payload):
    member_acme.shortcut_overrides = {"node.agent": "Alt+KeyG"}
    member_acme.save(update_fields=["shortcut_overrides"])

    response = client_for(member_acme).patch(
        PROFILE_URL, json.dumps({"shortcut_overrides": payload}), content_type="application/json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert response.json()["errors"] == [
        {"field": "shortcut_overrides", "value": None, "reason": ANY}
    ]
    member_acme.refresh_from_db()
    assert member_acme.shortcut_overrides == {"node.agent": "Alt+KeyG"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "shortcut_overrides", [[], {"node.agent": "\u0000"}], ids=["not-a-map", "nul-chord"]
)
def test_a_rejected_shortcut_patch_does_not_change_the_display_name(member_acme, shortcut_overrides):
    member_acme.display_name = "Keep"
    member_acme.shortcut_overrides = {"node.agent": "Alt+KeyG"}
    member_acme.save(update_fields=["display_name", "shortcut_overrides"])

    response = client_for(member_acme).patch(
        PROFILE_URL, {"display_name": "New", "shortcut_overrides": shortcut_overrides}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.shortcut_overrides) == ("Keep", {"node.agent": "Alt+KeyG"})


@pytest.mark.django_db
def test_patch_sets_the_display_name_and_shortcut_overrides_together(member_acme):
    response = client_for(member_acme).patch(
        PROFILE_URL,
        {"display_name": "Renamed", "shortcut_overrides": {"node.agent": "Alt+KeyG"}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert (response.json()["display_name"], response.json()["shortcut_overrides"]) == (
        "Renamed", {"node.agent": "Alt+KeyG"},
    )
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.shortcut_overrides) == ("Renamed", {"node.agent": "Alt+KeyG"})


@pytest.fixture
def profile_updated_receipts():
    receipts = []

    def record(sender, user, **kwargs):
        receipts.append(user.pk)

    profile_updated.connect(record, weak=False)
    yield receipts
    profile_updated.disconnect(record)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_signals"),
    [
        ({"shortcut_overrides": {"node.agent": "Alt+KeyG"}}, 0),
        ({"display_name": "Renamed"}, 1),
        ({"display_name": "Renamed", "shortcut_overrides": {"node.agent": "Alt+KeyG"}}, 1),
    ],
    ids=["shortcut-only", "display-name-only", "both"],
)
def test_only_a_display_name_change_announces_the_profile_not_a_shortcut_change(
    member_acme, profile_updated_receipts, body, expected_signals
):
    response = client_for(member_acme).patch(PROFILE_URL, body, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert profile_updated_receipts == [member_acme.pk] * expected_signals


@pytest.mark.django_db
@pytest.mark.parametrize(
    "raw_body", ['"shortcut_overrides"', '["display_name"]', "42"], ids=["string", "list", "number"]
)
def test_patch_rejects_a_body_that_is_not_an_object_before_reading_shortcut_overrides(member_acme, raw_body):
    member_acme.display_name = "Keep"
    member_acme.save(update_fields=["display_name"])

    response = client_for(member_acme).patch(PROFILE_URL, raw_body, content_type="application/json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert [error["field"] for error in response.json()["errors"]] == ["body"]
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.shortcut_overrides) == ("Keep", {})


@pytest.mark.django_db
def test_avatar_upload_and_delete(member_acme, tmp_media_root):
    client = client_for(member_acme)
    upload = SimpleUploadedFile("a.jpg", _image("JPEG"), content_type="image/jpeg")

    uploaded = client.post(AVATAR_URL, {"avatar": upload}, format="multipart")
    assert uploaded.status_code == status.HTTP_200_OK
    assert uploaded.json()["avatar_url"] is not None

    deleted = client.delete(AVATAR_URL)
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    member_acme.refresh_from_db()
    assert not member_acme.avatar


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("upload", "code"),
    [
        (lambda: SimpleUploadedFile("a.gif", _image("GIF"), content_type="image/gif"), "invalid_avatar"),
        (lambda: _png_upload("evil.png", b"this is not a real image, just some text\n"), "invalid_avatar"),
        (lambda: _png_upload("big.png", _image("PNG", size=(512, 512))), "avatar_too_large"),
        (lambda: None, "invalid"),
    ],
    ids=["gif", "text-disguised-as-png", "over-size-cap", "no-file"],
)
def test_avatar_upload_rejects_anything_but_a_small_real_image(member_acme, settings, tmp_media_root, upload, code):
    settings.AVATAR_MAX_SIZE = 1024
    file = upload()

    response = client_for(member_acme).post(AVATAR_URL, {"avatar": file} if file else {}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == code
    member_acme.refresh_from_db()
    assert not member_acme.avatar


# ---- Password change (request a ticket with the current password, then confirm) ----


def _ticket(client, password="StrongPass123!"):
    response = client.post(REQUEST_URL, {"current_password": password}, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["expires_in"] > 0
    return response.json()["ticket"]


@pytest.mark.django_db
@pytest.mark.parametrize(("body", "code"), [({"current_password": "WrongOne!"}, "invalid_current_password"), ({}, "invalid")])
def test_password_change_request_needs_the_current_password(member_acme, body, code):
    response = client_for(member_acme).post(REQUEST_URL, body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == code


@pytest.mark.django_db
def test_password_change_request_is_throttled(member_acme):
    cache.clear()
    client = client_for(member_acme)
    try:
        for _ in range(5):
            client.post(REQUEST_URL, {"current_password": "Bad!"}, format="json")

        response = client.post(REQUEST_URL, {"current_password": "Bad!"}, format="json")

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in response.headers
    finally:
        cache.clear()


@pytest.mark.django_db
def test_password_change_sets_the_password_and_replaces_the_users_sessions_and_keys(
    member_acme, orphan_user, issue_api_key
):
    RefreshToken.for_user(member_acme)
    _, own_key = issue_api_key(user=member_acme)
    _, other_users_key = issue_api_key(user=orphan_user)
    _, system_key = issue_api_key(user=None)
    client = client_for(member_acme)

    response = client.post(CONFIRM_URL, {"ticket": _ticket(client), "new_password": "BrandNewPass456!"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    # A fresh pair: access in the body, refresh only in the HttpOnly cookie.
    assert "refresh" not in response.json()
    assert response.cookies[REFRESH_COOKIE_NAME]["httponly"]
    fresh = APIClient()
    fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    assert fresh.get(PROFILE_URL).status_code == status.HTTP_200_OK
    member_acme.refresh_from_db()
    assert member_acme.check_password("BrandNewPass456!")
    assert BlacklistedToken.objects.filter(token__user=member_acme).exists()
    for key in (own_key, other_users_key, system_key):
        key.refresh_from_db()
    assert own_key.revoked_at is not None
    assert (other_users_key.revoked_at, system_key.revoked_at) == (None, None)


@pytest.mark.django_db
@pytest.mark.parametrize("ticket_source", ["spent", "unknown", "another-users"])
def test_password_change_confirm_needs_the_callers_unspent_ticket(member_acme, orphan_user, ticket_source):
    client = client_for(member_acme)
    if ticket_source == "spent":
        ticket = _ticket(client)
        client.post(CONFIRM_URL, {"ticket": ticket, "new_password": "BrandNewPass456!"}, format="json")
    elif ticket_source == "unknown":
        ticket = "totally-bogus"
    else:
        ticket = _ticket(client_for(orphan_user))
    password_before = member_acme.__class__.objects.get(pk=member_acme.pk).password

    response = client.post(CONFIRM_URL, {"ticket": ticket, "new_password": "EvilTakeover123!"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid_password_change_ticket"
    member_acme.refresh_from_db()
    assert member_acme.password == password_before


@pytest.mark.django_db
def test_password_change_confirm_rejects_a_weak_password_without_echoing_it(member_acme):
    client = client_for(member_acme)

    response = client.post(CONFIRM_URL, {"ticket": _ticket(client), "new_password": "123"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    password_errors = [error for error in response.json()["errors"] if error["field"] == "new_password"]
    assert password_errors
    assert all(error["value"] == "***" for error in password_errors)
    member_acme.refresh_from_db()
    assert member_acme.check_password("StrongPass123!")
