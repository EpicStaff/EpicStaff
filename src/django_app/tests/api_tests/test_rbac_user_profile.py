"""/api/profile/: the signed-in user's own profile, avatar, password change and guided tours."""

import io
import json
from datetime import timedelta
from unittest.mock import ANY
from urllib.parse import quote

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.refresh_cookie import refresh_cookie_name
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.signals import profile_updated
from tables.models import UserTourProgress

PROFILE_URL = "/api/profile/"
AVATAR_URL = "/api/profile/avatar/"
REQUEST_URL = "/api/profile/password-change/request/"
CONFIRM_URL = "/api/profile/password-change/confirm/"


def tour_url(tour_key: str) -> str:
    return f"/api/profile/tours/{quote(tour_key, safe='')}/complete/"


QUICK_START_TOUR_URL = tour_url("quick-start")


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
        ("post", QUICK_START_TOUR_URL, None, None),
    ],
    ids=[
        "get",
        "patch",
        "upload-avatar",
        "delete-avatar",
        "password-change-request",
        "password-change-confirm",
        "complete-tour",
    ],
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
@pytest.mark.parametrize(("method", "url"), [("get", PROFILE_URL), ("post", QUICK_START_TOUR_URL)])
def test_profile_needs_authentication(method, url):
    assert getattr(APIClient(), method)(url).status_code == status.HTTP_401_UNAUTHORIZED


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


EMPTY_SHORTCUTS = {"custom": [], "overrides": {}}
SAVED_SHORTCUTS = {
    "custom": [{"action": "node.task", "keys": "Shift+KeyT"}, {"action": "node.agent", "keys": None}],
    "overrides": {"node.python": "Shift+KeyY", "node.llm": None},
}


def shortcuts(custom, overrides=None):
    return {"custom": custom, "overrides": {} if overrides is None else overrides}


def overrides(mapping):
    return shortcuts([], mapping)


def custom_entry(action="node.task", keys="Shift+KeyT"):
    return {"action": action, "keys": keys}


def subgraph_entry(params, keys="Shift+KeyG"):
    return custom_entry(action="node.subgraph", keys=keys) | {"params": params}


def save_shortcuts(user, value):
    user.custom_shortcuts = value
    user.save(update_fields=["custom_shortcuts"])


@pytest.mark.django_db
def test_custom_shortcuts_default_to_empty_custom_and_overrides(member_acme):
    response = client_for(member_acme).get(PROFILE_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["custom_shortcuts"] == {"custom": [], "overrides": {}}


@pytest.mark.django_db
def test_patch_replaces_the_whole_shortcut_value(member_acme):
    save_shortcuts(
        member_acme,
        {
            "custom": [{"action": "editor.save", "keys": "Alt+KeyS"}, {"action": "node.task", "keys": "Shift+KeyT"}],
            "overrides": {"node.python": "Shift+KeyY"},
        },
    )
    replacement = {"custom": [{"action": "node.agent", "keys": None}], "overrides": {"node.llm": None}}

    response = client_for(member_acme).patch(PROFILE_URL, {"custom_shortcuts": replacement}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["custom_shortcuts"] == {
        "custom": [{"action": "node.agent", "keys": None}], "overrides": {"node.llm": None},
    }
    member_acme.refresh_from_db()
    assert member_acme.custom_shortcuts == {
        "custom": [{"action": "node.agent", "keys": None}], "overrides": {"node.llm": None},
    }


@pytest.mark.django_db
def test_patch_without_custom_shortcuts_keeps_them(member_acme):
    save_shortcuts(member_acme, SAVED_SHORTCUTS)

    response = client_for(member_acme).patch(PROFILE_URL, {"display_name": "Renamed"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["custom_shortcuts"] == SAVED_SHORTCUTS
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.custom_shortcuts) == ("Renamed", SAVED_SHORTCUTS)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        shortcuts([]),
        shortcuts([custom_entry(action="anything.the.frontend.wants")]),
        shortcuts([custom_entry(keys="Shift+KeyA"), custom_entry(keys="Shift+KeyB")]),
        shortcuts([custom_entry(action="node.agent"), custom_entry(action="node.agent", keys="Alt+KeyA")]),
        shortcuts([custom_entry(keys=None)]),
        shortcuts([custom_entry(action="node.agent", keys=None), custom_entry(keys=None)]),
        shortcuts([custom_entry(keys=None), custom_entry(keys="Shift+KeyT"), custom_entry(keys=None)]),
        shortcuts([custom_entry(action="x" * 64)]),
        shortcuts([custom_entry(keys="x" * 64)]),
        shortcuts([custom_entry(action=" !~", keys=" !~")]),
        shortcuts([custom_entry(keys=f"Shift+Key{index}") for index in range(100)]),
        shortcuts([custom_entry(keys=None) for _ in range(100)]),
        shortcuts([subgraph_entry({"flowId": 12})]),
        shortcuts([subgraph_entry({"flowName": "Main flow"})]),
        shortcuts([subgraph_entry({f"param{index}": index for index in range(5)})]),
        shortcuts([subgraph_entry({"x" * 64: "y" * 64})]),
        shortcuts([subgraph_entry({" !~": " !~"})]),
        shortcuts([subgraph_entry({"flowId": 0})]),
        shortcuts([subgraph_entry({"flowId": 2**53 - 1})]),
        shortcuts([
            custom_entry(),
            subgraph_entry({"flowId": 12}, keys="Shift+KeyA"),
            subgraph_entry({"flowId": 13}, keys=None),
        ]),
        overrides({"node.python": "Shift+KeyY"}),
        overrides({"node.python": None}),
        overrides({"node.python": None, "node.llm": None}),
        overrides({f"node.action{index}": f"Shift+Key{index}" for index in range(100)}),
        overrides({f"node.action{index}": None for index in range(100)}),
        overrides({"x" * 64: "y" * 64}),
        overrides({" !~": " !~"}),
        shortcuts([custom_entry(keys=None)], {"node.python": "Shift+KeyT"}),
        shortcuts([custom_entry(keys="Shift+KeyA")], {"node.python": "Shift+KeyB", "node.llm": None}),
    ],
    ids=[
        "empty", "unknown-action", "two-keys", "same-action-twice", "null-keys", "repeated-null-keys",
        "null-keys-beside-a-chord", "action-at-limit", "keys-at-limit", "printable-ascii-edges",
        "entries-at-limit", "entries-at-limit-all-null", "params-int", "params-string", "params-at-limit",
        "param-name-and-value-at-limit", "param-printable-ascii-edges", "param-int-zero", "param-int-at-limit",
        "entries-with-and-without-params", "override-chord", "override-null", "overrides-all-null",
        "overrides-at-limit", "overrides-at-limit-all-null", "override-action-and-chord-at-limit",
        "override-printable-ascii-edges", "override-chord-beside-a-null-custom-keys",
        "overrides-and-custom-with-different-chords",
    ],
)
def test_patch_accepts_custom_shortcuts_up_to_the_limits(member_acme, payload):
    response = client_for(member_acme).patch(PROFILE_URL, {"custom_shortcuts": payload}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["custom_shortcuts"] == payload
    member_acme.refresh_from_db()
    assert member_acme.custom_shortcuts == payload


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "Shift+KeyA",
        {},
        {"node.agent": "Shift+KeyA"},
        {"custom": []},
        {"overrides": {}},
        {"custom": [], "overrides": {}, "extra": {}},
        shortcuts(None),
        shortcuts({}),
        shortcuts("Shift+KeyA"),
        shortcuts([None]),
        shortcuts(["Shift+KeyA"]),
        shortcuts([["node.task", "Shift+KeyT"]]),
        shortcuts([{"action": "node.task"}]),
        shortcuts([{"keys": "Shift+KeyT"}]),
        shortcuts([custom_entry() | {"extra": "x"}]),
        shortcuts([custom_entry(action=1)]),
        shortcuts([custom_entry(action=None)]),
        shortcuts([custom_entry(keys=1)]),
        shortcuts([custom_entry(keys=["Shift+KeyA"])]),
        shortcuts([custom_entry(action="")]),
        shortcuts([custom_entry(keys="")]),
        shortcuts([custom_entry(action="x" * 65)]),
        shortcuts([custom_entry(keys="x" * 65)]),
        shortcuts([custom_entry(keys=None) for _ in range(101)]),
        shortcuts([custom_entry(keys="\u0000")]),
        shortcuts([custom_entry(action="node.\u0000")]),
        shortcuts([custom_entry(keys="\ud800")]),
        shortcuts([custom_entry(action="node.\ud800")]),
        shortcuts([custom_entry(keys="Shift+КейА")]),
        shortcuts([custom_entry(keys="Shift+\tKeyA")]),
        shortcuts([custom_entry(keys="Shift+KeyA\u007f")]),
        shortcuts([custom_entry(action="node.agent"), custom_entry(action="node.task")]),
        shortcuts([custom_entry(keys=None), custom_entry(action="node.agent"), custom_entry(keys=None), custom_entry()]),
        shortcuts([custom_entry(keys=["Shift+KeyA"]), custom_entry(keys=["Shift+KeyA"])]),
        shortcuts([subgraph_entry([12])]),
        shortcuts([subgraph_entry("flowId=12")]),
        shortcuts([subgraph_entry(None)]),
        shortcuts([subgraph_entry(12)]),
        shortcuts([subgraph_entry({})]),
        shortcuts([subgraph_entry({f"param{index}": index for index in range(6)})]),
        shortcuts([subgraph_entry({"flowId": 12}) | {"extra": "x"}]),
        shortcuts([subgraph_entry({"": 12})]),
        shortcuts([subgraph_entry({"x" * 65: 12})]),
        shortcuts([subgraph_entry({"flowName": ""})]),
        shortcuts([subgraph_entry({"flowName": "x" * 65})]),
        shortcuts([subgraph_entry({"flowId": True})]),
        shortcuts([subgraph_entry({"flowId": False})]),
        shortcuts([subgraph_entry({"flowId": 12.0})]),
        shortcuts([subgraph_entry({"flowId": 12.5})]),
        shortcuts([subgraph_entry({"flowId": {"id": 12}})]),
        shortcuts([subgraph_entry({"flowId": [12]})]),
        shortcuts([subgraph_entry({"flowId": None})]),
        shortcuts([subgraph_entry({"flowId": -1})]),
        shortcuts([subgraph_entry({"flowId": 2**53})]),
        shortcuts([subgraph_entry({"flow\u0000Id": 12})]),
        shortcuts([subgraph_entry({"flowName": "Main\u0000"})]),
        shortcuts([subgraph_entry({"flowІd": 12})]),
        shortcuts([subgraph_entry({"flowName": "Головний"})]),
        shortcuts([subgraph_entry({"flowName": "Main\tflow"})]),
        shortcuts([custom_entry(), subgraph_entry({"flowId": 12}, keys="Shift+KeyT")]),
        {"custom": [], "overrides": None},
        overrides([]),
        overrides(["node.python", "Shift+KeyY"]),
        overrides("node.python=Shift+KeyY"),
        overrides({f"node.action{index}": None for index in range(101)}),
        overrides({"": "Shift+KeyY"}),
        overrides({"x" * 65: "Shift+KeyY"}),
        overrides({"node.python": ""}),
        overrides({"node.python": "x" * 65}),
        overrides({"node.python": 1}),
        overrides({"node.python": True}),
        overrides({"node.python": ["Shift+KeyY"]}),
        overrides({"node.python": {"keys": "Shift+KeyY"}}),
        overrides({"node.\u0000": "Shift+KeyY"}),
        overrides({"node.python": "Shift+KeyY\u0000"}),
        overrides({"node.пітон": "Shift+KeyY"}),
        overrides({"node.python": "Shift+КейY"}),
        overrides({"node.python": "Shift+KeyY", "node.llm": "Shift+KeyY"}),
        shortcuts([custom_entry(keys="Shift+KeyY")], {"node.python": "Shift+KeyY"}),
        shortcuts([custom_entry(action="node.python", keys="Shift+KeyY")], {"node.python": "Shift+KeyY"}),
    ],
    ids=[
        "null", "list", "string", "empty-object", "old-flat-map", "missing-overrides", "missing-custom",
        "extra-top-level-key", "custom-null", "custom-object", "custom-string", "item-null", "item-string",
        "item-list", "item-missing-keys", "item-missing-action", "item-extra-key", "non-string-action",
        "null-action", "non-string-keys", "list-keys", "empty-action", "empty-keys", "action-over-limit",
        "keys-over-limit", "entries-over-limit", "nul-keys", "nul-action", "lone-surrogate-keys",
        "lone-surrogate-action", "non-ascii-keys", "tab-in-keys", "delete-char-in-keys", "duplicate-keys",
        "duplicate-keys-between-nulls", "duplicate-non-hashable-keys", "params-list", "params-string",
        "params-null", "params-int", "params-empty", "params-over-limit", "item-with-params-and-extra-key",
        "empty-param-name", "param-name-over-limit", "empty-param-string", "param-string-over-limit",
        "param-true", "param-false", "param-whole-float", "param-float", "param-object", "param-list",
        "param-null", "param-negative-int", "param-int-over-limit", "nul-param-name", "nul-param-string",
        "non-ascii-param-name", "non-ascii-param-string", "tab-in-param-string", "duplicate-keys-with-params",
        "overrides-null", "overrides-list", "overrides-pair-list", "overrides-string", "overrides-over-limit",
        "empty-override-action", "override-action-over-limit", "empty-override-chord", "override-chord-over-limit",
        "int-override-chord", "bool-override-chord", "list-override-chord", "object-override-chord",
        "nul-override-action", "nul-override-chord", "non-ascii-override-action", "non-ascii-override-chord",
        "duplicate-chord-between-overrides", "duplicate-chord-between-override-and-custom",
        "duplicate-chord-between-override-and-custom-of-the-same-action",
    ],
)
def test_patch_rejects_a_malformed_shortcut_value(member_acme, payload):
    save_shortcuts(member_acme, SAVED_SHORTCUTS)

    response = client_for(member_acme).patch(
        PROFILE_URL, json.dumps({"custom_shortcuts": payload}), content_type="application/json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert response.json()["errors"] == [
        {"field": "custom_shortcuts", "value": None, "reason": ANY}
    ]
    member_acme.refresh_from_db()
    assert member_acme.custom_shortcuts == SAVED_SHORTCUTS


@pytest.mark.django_db
@pytest.mark.parametrize(
    "custom_shortcuts",
    [
        [],
        {"node.agent": "Alt+KeyG"},
        {"custom": []},
        shortcuts([custom_entry(keys="\u0000")]),
        shortcuts([custom_entry(), custom_entry(action="node.agent")]),
        shortcuts([subgraph_entry({"flowId": True})]),
        shortcuts([subgraph_entry({"flowId": {"id": 12}})]),
        overrides({"node.python": 1}),
        shortcuts([custom_entry()], {"node.python": "Shift+KeyT"}),
    ],
    ids=[
        "not-an-object", "old-flat-map", "missing-overrides", "nul-keys", "duplicate-keys", "param-true",
        "param-object", "non-string-override-chord", "duplicate-chord-between-override-and-custom",
    ],
)
def test_a_rejected_shortcut_patch_does_not_change_the_display_name(member_acme, custom_shortcuts):
    member_acme.display_name = "Keep"
    member_acme.custom_shortcuts = SAVED_SHORTCUTS
    member_acme.save(update_fields=["display_name", "custom_shortcuts"])

    response = client_for(member_acme).patch(
        PROFILE_URL, {"display_name": "New", "custom_shortcuts": custom_shortcuts}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.custom_shortcuts) == ("Keep", SAVED_SHORTCUTS)


@pytest.mark.django_db
def test_patch_ignores_unknown_fields_next_to_saved_shortcuts(member_acme):
    save_shortcuts(member_acme, SAVED_SHORTCUTS)

    response = client_for(member_acme).patch(
        PROFILE_URL, {"not_a_profile_field": shortcuts([custom_entry(keys="Alt+KeyZ")])}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["custom_shortcuts"] == SAVED_SHORTCUTS
    assert "not_a_profile_field" not in response.json()
    member_acme.refresh_from_db()
    assert member_acme.custom_shortcuts == SAVED_SHORTCUTS


@pytest.mark.django_db
def test_patch_sets_the_display_name_and_custom_shortcuts_together(member_acme):
    response = client_for(member_acme).patch(
        PROFILE_URL,
        {"display_name": "Renamed", "custom_shortcuts": SAVED_SHORTCUTS},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert (response.json()["display_name"], response.json()["custom_shortcuts"]) == (
        "Renamed", SAVED_SHORTCUTS,
    )
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.custom_shortcuts) == ("Renamed", SAVED_SHORTCUTS)


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
        ({"custom_shortcuts": SAVED_SHORTCUTS}, 0),
        ({"display_name": "Renamed"}, 1),
        ({"display_name": "Renamed", "custom_shortcuts": SAVED_SHORTCUTS}, 1),
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
    "raw_body", ['"custom_shortcuts"', '["display_name"]', "42"], ids=["string", "list", "number"]
)
def test_patch_rejects_a_body_that_is_not_an_object_before_reading_custom_shortcuts(member_acme, raw_body):
    member_acme.display_name = "Keep"
    member_acme.save(update_fields=["display_name"])

    response = client_for(member_acme).patch(PROFILE_URL, raw_body, content_type="application/json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid"
    assert [error["field"] for error in response.json()["errors"]] == ["body"]
    member_acme.refresh_from_db()
    assert (member_acme.display_name, member_acme.custom_shortcuts) == ("Keep", EMPTY_SHORTCUTS)


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


@pytest.mark.usefixtures("refresh_cookie_secure")
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
    assert response.cookies[refresh_cookie_name()]["httponly"]
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


# ---- Guided tours ----


def _store_completed_tours(user, tour_keys):
    UserTourProgress.objects.bulk_create(
        [UserTourProgress(user=user, tour_key=tour_key, completed_at=timezone.now()) for tour_key in tour_keys]
    )


def _numbered_tour_keys(count):
    return [f"tour-{number}" for number in range(count)]


@pytest.mark.django_db
def test_a_fresh_user_has_no_completed_tours(member_acme):
    assert client_for(member_acme).get(PROFILE_URL).json()["completed_tours"] == []


@pytest.mark.django_db
def test_completing_a_tour_records_it_and_returns_the_profile(member_acme):
    client = client_for(member_acme)
    updated_at_before = member_acme.updated_at

    response = client.post(QUICK_START_TOUR_URL)

    assert response.status_code == status.HTTP_200_OK
    assert (response.json()["id"], response.json()["completed_tours"]) == (member_acme.id, ["quick-start"])
    assert client.get(PROFILE_URL).json()["completed_tours"] == ["quick-start"]
    member_acme.refresh_from_db()
    # Finishing a tour is not a profile edit.
    assert member_acme.updated_at == updated_at_before


@pytest.mark.django_db
def test_completing_a_tour_again_keeps_the_first_completion_time(member_acme):
    earlier = timezone.now() - timedelta(days=30)
    UserTourProgress.objects.create(user=member_acme, tour_key="quick-start", completed_at=earlier)

    response = client_for(member_acme).post(QUICK_START_TOUR_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["completed_tours"] == ["quick-start"]
    stored = UserTourProgress.objects.filter(user=member_acme).values_list("tour_key", "completed_at")
    assert list(stored) == [("quick-start", earlier)]


@pytest.mark.django_db
def test_completed_tours_are_listed_in_key_order(member_acme):
    client = client_for(member_acme)
    for tour_key in ["welcome", "quickstart", "quick-start", "flows"]:
        assert client.post(tour_url(tour_key)).status_code == status.HTTP_200_OK

    assert client.get(PROFILE_URL).json()["completed_tours"] == ["flows", "quick-start", "quickstart", "welcome"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tour_key",
    ["a", "a" * 64, "quick-start", "flows-v2", "2026"],
    ids=["one-character", "64-characters", "hyphenated", "letters-and-digits", "digits-only"],
)
def test_a_well_formed_tour_key_is_accepted(member_acme, tour_key):
    response = client_for(member_acme).post(tour_url(tour_key))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["completed_tours"] == [tour_key]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tour_key",
    [
        "Quick",
        "a" * 65,
        "a--b",
        "-quick",
        "quick-",
        "quick_start",
        "quick start",
        "тур",
        "café",
        "quick-start\n",
    ],
    ids=[
        "uppercase",
        "65-characters",
        "double-hyphen",
        "leading-hyphen",
        "trailing-hyphen",
        "underscore",
        "space",
        "cyrillic",
        "accented-latin",
        "trailing-newline",
    ],
)
def test_a_malformed_tour_key_is_rejected_and_nothing_is_stored(member_acme, tour_key):
    response = client_for(member_acme).post(tour_url(tour_key))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = response.json()
    assert body["code"] == "invalid"
    assert [(error["field"], error["value"]) for error in body["errors"]] == [("tour_key", tour_key)]
    assert not UserTourProgress.objects.filter(user=member_acme).exists()


@pytest.mark.django_db
def test_the_fiftieth_tour_is_accepted(member_acme):
    _store_completed_tours(member_acme, _numbered_tour_keys(49))

    response = client_for(member_acme).post(tour_url("the-last-one"))

    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()["completed_tours"]) == 50
    assert "the-last-one" in response.json()["completed_tours"]


@pytest.mark.django_db
def test_a_new_tour_beyond_fifty_is_rejected_and_nothing_is_stored(member_acme):
    _store_completed_tours(member_acme, _numbered_tour_keys(50))

    response = client_for(member_acme).post(tour_url("one-too-many"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "tour_limit_exceeded"
    assert UserTourProgress.objects.filter(user=member_acme).count() == 50
    assert not UserTourProgress.objects.filter(user=member_acme, tour_key="one-too-many").exists()


@pytest.mark.django_db
def test_completing_an_already_completed_tour_at_the_limit_still_succeeds(member_acme):
    _store_completed_tours(member_acme, _numbered_tour_keys(50))

    response = client_for(member_acme).post(tour_url("tour-7"))

    assert response.status_code == status.HTTP_200_OK
    assert UserTourProgress.objects.filter(user=member_acme).count() == 50


@pytest.mark.django_db
def test_the_limit_counts_only_the_callers_own_tours(member_acme, orphan_user):
    _store_completed_tours(orphan_user, _numbered_tour_keys(50))

    response = client_for(member_acme).post(QUICK_START_TOUR_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["completed_tours"] == ["quick-start"]


@pytest.mark.django_db
def test_completing_a_tour_neither_changes_nor_shows_another_users_tours(member_acme, orphan_user):
    earlier = timezone.now() - timedelta(days=30)
    UserTourProgress.objects.create(user=orphan_user, tour_key="quick-start", completed_at=earlier)
    UserTourProgress.objects.create(user=orphan_user, tour_key="flows", completed_at=earlier)

    response = client_for(member_acme).post(QUICK_START_TOUR_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["completed_tours"] == ["quick-start"]
    others = UserTourProgress.objects.filter(user=orphan_user).order_by("tour_key")
    assert list(others.values_list("tour_key", "completed_at")) == [("flows", earlier), ("quick-start", earlier)]


@pytest.mark.django_db
def test_the_profile_reads_completed_tours_in_a_fixed_number_of_queries(member_acme):
    client = client_for(member_acme)
    _store_completed_tours(member_acme, ["quick-start"])
    with CaptureQueriesContext(connection) as one_tour:
        client.get(PROFILE_URL)

    _store_completed_tours(member_acme, _numbered_tour_keys(9))
    with CaptureQueriesContext(connection) as ten_tours:
        assert len(client.get(PROFILE_URL).json()["completed_tours"]) == 10

    assert len(ten_tours.captured_queries) == len(one_tour.captured_queries)


@pytest.mark.django_db
def test_a_user_api_key_completes_a_tour_for_its_owner(member_acme, issue_api_key):
    raw, _ = issue_api_key(user=member_acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)

    response = client.post(QUICK_START_TOUR_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == member_acme.id
    stored_keys = UserTourProgress.objects.filter(user=member_acme).values_list("tour_key", flat=True)
    assert list(stored_keys) == ["quick-start"]


@pytest.mark.django_db
def test_completing_a_tour_is_post_only(member_acme):
    assert client_for(member_acme).get(QUICK_START_TOUR_URL).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_completing_a_tour_keeps_the_active_org_context(api_client, jwt_tokens, default_org):
    # The response is the full profile, so it carries the same active-org data
    # as GET /api/profile/ for the same header.
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    response = api_client.post(QUICK_START_TOUR_URL, HTTP_X_ORGANIZATION_ID=str(default_org.id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["completed_tours"] == ["quick-start"]
    assert body["active_organization_id"] == default_org.id
    assert body["active_permissions"]["role"]["name"] == "Org Admin"
