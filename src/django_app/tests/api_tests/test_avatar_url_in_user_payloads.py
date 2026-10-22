"""Every payload that shows a user shows the same relative avatar URL, and never the storage key.

The URL is `/api/users/<id>/avatar/?v=<version>`, relative so it does not depend on
the host the request came in on, and versioned by the stored file's random stem so
a new upload changes it. The raw `avatar` field (a bucket key) is not in any payload.
"""

import pytest
from rest_framework import status

from rbac.authorship import represent_user_summary
from tables.graph_collab.utils import build_editor_info
from tests.avatar_helpers import point_avatar_at
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

VERSION = "9c4e1f0a7b2d4e6f8a1c3e5b7d9f0a2c"


@pytest.fixture
def admin_with_avatar(admin_acme):
    """Acme's org admin, so they show up in every user listing; the column alone is enough."""
    point_avatar_at(admin_acme, f"avatars/{admin_acme.id}/{VERSION}.png")
    return admin_acme


@pytest.fixture
def expected_url(admin_with_avatar):
    return f"/api/users/{admin_with_avatar.id}/avatar/?v={VERSION}"


def _profile(body, user):
    return body


def _admin_users_row(body, user):
    return next(row for row in body["results"] if row["id"] == user.id)


def _membership_user(body, user):
    return next(row["user"] for row in body["results"] if row["user"]["id"] == user.id)


def _api_key_owner(body, user):
    return next(row["owner"] for row in body["results"] if row["owner"]["id"] == user.id)


def _organization_admin(body, user):
    return next(admin for org in body["results"] for admin in org["admins"] if admin["id"] == user.id)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("as_target", "url", "find_user"),
    [
        (True, "/api/profile/", _profile),
        (False, "/api/admin/users/", _admin_users_row),
        (False, "/api/admin/memberships/", _membership_user),
        (False, "/api/admin/api-keys/", _api_key_owner),
        (False, "/api/admin/organizations/", _organization_admin),
    ],
    ids=["profile", "admin-users", "memberships", "api-key-owner", "organization-admins"],
)
def test_user_payloads_carry_the_relative_versioned_avatar_url(
    client_as, superadmin, admin_with_avatar, expected_url, issue_api_key, as_target, url, find_user
):
    issue_api_key(user=admin_with_avatar)
    client = client_as(admin_with_avatar if as_target else superadmin)

    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    shown = find_user(response.json(), admin_with_avatar)
    assert shown["avatar_url"] == expected_url
    assert "avatar" not in shown


@pytest.mark.django_db
def test_assignable_users_carry_the_avatar_url(client_as, admin_acme, member_only):
    point_avatar_at(member_only, f"avatars/{member_only.id}/{VERSION}.png")

    body = client_as(admin_acme).get("/api/admin/memberships/assignable-users/").json()

    row = next(row for row in body["results"] if row["id"] == member_only.id)
    assert row["avatar_url"] == f"/api/users/{member_only.id}/avatar/?v={VERSION}"
    assert "avatar" not in row


@pytest.mark.django_db
def test_author_summaries_and_collaborator_presence_carry_the_avatar_url(admin_with_avatar, expected_url):
    assert represent_user_summary(admin_with_avatar)["avatar_url"] == expected_url
    assert build_editor_info(admin_with_avatar).avatar_url == expected_url


@pytest.mark.django_db
def test_a_user_without_an_avatar_has_a_null_url(client_as, member_only):
    body = client_as(member_only).get("/api/profile/").json()

    assert body["avatar_url"] is None
    assert represent_user_summary(member_only)["avatar_url"] is None
    assert build_editor_info(member_only).avatar_url is None
