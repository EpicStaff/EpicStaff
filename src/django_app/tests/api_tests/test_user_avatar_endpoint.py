"""GET /api/users/<id>/avatar/: an avatar is served only to a caller who may see its user.

A caller sees their own avatar, any avatar when superadmin, a superadmin's avatar,
and the avatar of anyone sharing an active organization with them. Every refusal --
user not visible, unknown, without an avatar, a stale `v`, an object missing from
storage -- is the same 404 body, so the endpoint cannot reveal which users exist or
have an avatar. A 304 is only ever answered after that access check.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import Organization, OrganizationUser
from tests.avatar_helpers import image_bytes, point_avatar_at, store_avatar
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

VERSION = "5f0c3a9e2b7d4c1e8a6f0b3d2c1e4f5a"
STALE_VERSION = "0123456789abcdef0123456789abcdef"
PNG = image_bytes("PNG")
IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "private, no-cache"


def avatar_url(user_id, version=VERSION):
    base = f"/api/users/{user_id}/avatar/"
    return base if version is None else f"{base}?v={version}"


@pytest.fixture
def colleague(db, django_user_model, acme, role_member):
    """A member of Acme with a PNG avatar stored as VERSION."""
    user = django_user_model.objects.create_user(email="avatar-colleague@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    store_avatar(user, PNG, VERSION)
    return user


@pytest.fixture
def outsider(db, django_user_model, beta, role_member):
    """A member of Beta only: shares no organization with Acme's members."""
    user = django_user_model.objects.create_user(email="avatar-outsider@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def superadmin_with_avatar(superadmin):
    store_avatar(superadmin, PNG, VERSION)
    return superadmin


# ---- who may see it ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    "requester",
    ["colleague", "member_only", "superadmin"],
    ids=["self", "member-of-a-shared-active-org", "superadmin-requester"],
)
def test_a_caller_who_may_see_the_user_gets_the_image(request, client_as, colleague, requester):
    response = client_as(request.getfixturevalue(requester)).get(avatar_url(colleague.id))

    assert response.status_code == status.HTTP_200_OK
    assert response.content == PNG


@pytest.mark.django_db
def test_a_superadmins_avatar_is_visible_to_a_user_of_any_organization(
    client_as, superadmin_with_avatar, outsider
):
    response = client_as(outsider).get(avatar_url(superadmin_with_avatar.id))

    assert response.status_code == status.HTTP_200_OK
    assert response.content == PNG


@pytest.mark.django_db
def test_a_user_of_another_organization_gets_404(client_as, colleague, outsider):
    response = client_as(outsider).get(avatar_url(colleague.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "avatar_not_found"


@pytest.mark.django_db
def test_sharing_only_an_inactive_organization_gets_404(client_as, colleague, outsider, role_member):
    dormant = Organization.objects.create(name="Dormant-avatar-org", is_active=False)
    OrganizationUser.objects.create(user=colleague, org=dormant, role=role_member)
    OrganizationUser.objects.create(user=outsider, org=dormant, role=role_member)

    response = client_as(outsider).get(avatar_url(colleague.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "avatar_not_found"


@pytest.mark.django_db
def test_an_unauthenticated_request_gets_401(colleague):
    assert APIClient().get(avatar_url(colleague.id)).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_real_jwt_and_user_api_key_credentials_are_accepted(colleague, member_only, issue_api_key):
    """The view declares its own authenticators; both real credential kinds must reach it."""
    jwt_client = APIClient()
    jwt_client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(member_only).access_token}")
    raw_key, _ = issue_api_key(user=member_only)
    key_client = APIClient()
    key_client.credentials(HTTP_X_API_KEY=raw_key)

    assert jwt_client.get(avatar_url(colleague.id)).status_code == status.HTTP_200_OK
    assert key_client.get(avatar_url(colleague.id)).status_code == status.HTTP_200_OK


# ---- one 404 for every refusal ----


@pytest.mark.django_db
def test_every_refusal_is_the_same_404(client_as, colleague, outsider, member_only, admin_acme):
    point_avatar_at(admin_acme, f"avatars/{admin_acme.id}/{VERSION}.png")  # names an object never stored
    member_client = client_as(member_only)
    refusals = {
        "not-visible": client_as(outsider).get(avatar_url(colleague.id)),
        "unknown-user": member_client.get(avatar_url(999_999_999)),
        "no-avatar": client_as(outsider).get(avatar_url(outsider.id)),
        "stale-version": member_client.get(avatar_url(colleague.id, STALE_VERSION)),
        "missing-object": member_client.get(avatar_url(admin_acme.id)),
    }

    assert {name: response.status_code for name, response in refusals.items()} == dict.fromkeys(
        refusals, status.HTTP_404_NOT_FOUND
    )
    bodies = {response.content for response in refusals.values()}
    assert len(bodies) == 1, bodies
    assert refusals["not-visible"].json()["code"] == "avatar_not_found"


# ---- caching ----


@pytest.mark.django_db
def test_a_versioned_url_is_cached_forever(client_as, colleague):
    response = client_as(colleague).get(avatar_url(colleague.id))

    assert response["Cache-Control"] == IMMUTABLE
    assert response["ETag"] == f'"{VERSION}"'


@pytest.mark.django_db
def test_an_unversioned_url_must_be_revalidated(client_as, colleague):
    response = client_as(colleague).get(avatar_url(colleague.id, None))

    assert response.status_code == status.HTTP_200_OK
    assert response.content == PNG
    assert response["Cache-Control"] == REVALIDATE
    assert response["ETag"] == f'"{VERSION}"'


@pytest.mark.django_db
@pytest.mark.parametrize(
    "if_none_match",
    [f'"{VERSION}"', f'W/"{VERSION}"', "*", f'"{STALE_VERSION}", "{VERSION}"'],
    ids=["exact", "weak", "any", "list"],
)
@pytest.mark.parametrize(("version", "cache_control"), [(VERSION, IMMUTABLE), (None, REVALIDATE)], ids=["v", "no-v"])
def test_a_matching_if_none_match_gets_304_without_a_body(client_as, colleague, if_none_match, version, cache_control):
    response = client_as(colleague).get(avatar_url(colleague.id, version), HTTP_IF_NONE_MATCH=if_none_match)

    assert response.status_code == status.HTTP_304_NOT_MODIFIED
    assert response.content == b""
    assert response["ETag"] == f'"{VERSION}"'
    assert response["Cache-Control"] == cache_control


@pytest.mark.django_db
def test_a_different_etag_gets_the_image(client_as, colleague):
    response = client_as(colleague).get(avatar_url(colleague.id, None), HTTP_IF_NONE_MATCH=f'"{STALE_VERSION}"')

    assert response.status_code == status.HTTP_200_OK
    assert response.content == PNG


@pytest.mark.django_db
@pytest.mark.parametrize("if_none_match", [f'"{VERSION}"', "*"], ids=["exact", "any"])
def test_a_caller_who_may_not_see_the_user_never_gets_304(client_as, colleague, outsider, if_none_match):
    response = client_as(outsider).get(avatar_url(colleague.id), HTTP_IF_NONE_MATCH=if_none_match)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "avatar_not_found"


# ---- what is sent ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("extension", "content", "content_type"),
    [
        (".png", PNG, "image/png"),
        (".jpg", image_bytes("JPEG"), "image/jpeg"),
        (".gif", image_bytes("GIF"), "application/octet-stream"),
    ],
    ids=["png", "jpeg", "unknown-extension"],
)
def test_the_content_type_follows_the_stored_key_and_is_never_sniffed(
    client_as, member_only, extension, content, content_type
):
    store_avatar(member_only, content, VERSION, extension)

    response = client_as(member_only).get(avatar_url(member_only.id))

    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response["Content-Type"] == content_type
    assert response["Content-Length"] == str(len(content))
    assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_an_image_accept_header_is_not_refused_with_406(client_as, colleague, outsider):
    """Browsers send `Accept: image/*` for <img>; neither the image nor the 404 may turn into a 406."""
    served = client_as(colleague).get(avatar_url(colleague.id), HTTP_ACCEPT="image/png")
    refused = client_as(outsider).get(avatar_url(colleague.id), HTTP_ACCEPT="image/png")

    assert served.status_code == status.HTTP_200_OK
    assert refused.status_code == status.HTTP_404_NOT_FOUND
