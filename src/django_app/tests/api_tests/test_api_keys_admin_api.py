"""/api/admin/api-keys/: org admins see and revoke the keys of their orgs' members."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import ApiKey, OrganizationUser
from rbac.identity.api_keys.generator import ApiKeyGenerator

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = "/api/admin/api-keys/"


def detail_url(key_id):
    return f"{LIST_URL}{key_id}/"


def revoke_url(key_id):
    return f"{LIST_URL}{key_id}/revoke/"


@pytest.fixture
def make_key(db):
    def _make(owner, name="k"):
        return ApiKey.objects.create(
            name=name,
            key_type=ApiKey.KeyType.USER,
            prefix="es-000000000",
            key_hash=f"hash-{owner.id}-{name}",
            created_by=owner,
        )

    return _make


@pytest.fixture
def acme_member(db, django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(email="acme-keyholder@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_anonymous_401():
    assert APIClient().get(LIST_URL).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_denied_without_api_keys_read(client_as, member_only):
    assert client_as(member_only).get(LIST_URL).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_list_shows_member_keys_without_secrets_and_needs_no_org_header(client_as, admin_acme, acme_member, acme, make_key):
    make_key(acme_member, name="laptop")

    response = client_as(admin_acme).get(LIST_URL)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    (row,) = body["results"]
    assert (row["name"], row["owner"]["email"], row["org_ids"]) == ("laptop", "acme-keyholder@example.com", [acme.id])
    assert "key_hash" not in row


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "status_code"),
    [({"org_ids": "beta"}, 403), ({"status": "bogus"}, 400), ({"user": "abc"}, 400)],
    ids=["forbidden-org", "bad-status", "bad-user"],
)
def test_list_rejects_bad_filters(client_as, admin_acme, beta, query, status_code):
    if query.get("org_ids") == "beta":
        query = {"org_ids": str(beta.id)}

    response = client_as(admin_acme).get(LIST_URL, query)

    assert response.status_code == status_code
    if status_code == 400:
        assert response.json()["code"] == "invalid"


@pytest.mark.django_db
def test_revoke_then_delete_a_members_key(client_as, admin_acme, acme_member, acme, make_key):
    key = make_key(acme_member, name="target")
    client = client_as(admin_acme)

    revoked = client.post(revoke_url(key.pk))
    assert revoked.status_code == status.HTTP_200_OK
    assert (revoked.json()["status"], revoked.json()["org_ids"]) == ("revoked", [acme.id])

    assert client.delete(detail_url(key.pk)).status_code == status.HTTP_204_NO_CONTENT
    assert not ApiKey.objects.filter(pk=key.pk).exists()


@pytest.mark.django_db
def test_superadmin_can_revoke_a_superadmin_key(client_as, superadmin, django_user_model, make_key):
    peer = django_user_model.objects.create_user(email="peer-platform@example.com", password="StrongPass123!", is_superadmin=True)
    key = make_key(peer, name="peer")

    response = client_as(superadmin).post(revoke_url(key.pk))

    assert (response.status_code, response.json()["status"]) == (status.HTTP_200_OK, "revoked")


@pytest.fixture
def admin_beta_member_acme(db, django_user_model, acme, beta, role_org_admin, role_member):
    """Org Admin of beta (clears the API_KEYS door gate) and a plain Member of acme
    (api_keys=0 there), the only org the key owner belongs to."""
    user = django_user_model.objects.create_user(email="admin-beta-member-acme-key@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["revoke", "delete"])
@pytest.mark.parametrize(
    "situation",
    ["superadmins-key", "other-orgs-key", "no-api-keys-bits-in-owners-org"],
)
def test_a_key_the_caller_may_not_manage_looks_like_it_does_not_exist(
    request, client_as, admin_acme, superadmin, acme, beta, role_org_admin, role_member,
    acme_member, django_user_model, make_key, situation, action,
):
    if situation == "superadmins-key":
        # A superadmin's keys are hidden from delegated admins, even in a shared org.
        OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
        key, caller = make_key(superadmin, name="platform"), admin_acme
    elif situation == "other-orgs-key":
        outsider = django_user_model.objects.create_user(email="far-away@example.com", password="StrongPass123!")
        OrganizationUser.objects.create(user=outsider, org=beta, role=role_member)
        key, caller = make_key(outsider, name="far"), admin_acme
    else:
        key, caller = make_key(acme_member, name="invisible"), request.getfixturevalue("admin_beta_member_acme")
    client = client_as(caller)

    listed = [row["name"] for row in client.get(LIST_URL).json()["results"]]
    response = client.post(revoke_url(key.pk)) if action == "revoke" else client.delete(detail_url(key.pk))

    assert key.name not in listed
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "api_key_not_found"
    key.refresh_from_db()
    assert key.revoked_at is None


@pytest.mark.django_db
def test_api_key_auth_is_refused_on_every_action(admin_acme, acme_member, make_key):
    raw = "es-blocked-raw-value-for-deny-test"
    ApiKey.objects.create(
        name="caller",
        key_type=ApiKey.KeyType.USER,
        prefix=ApiKeyGenerator.prefix_of(raw),
        key_hash=ApiKeyGenerator.hash_key(raw),
        created_by=admin_acme,
    )
    target = make_key(acme_member, name="target")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)

    assert client.get(LIST_URL).status_code == status.HTTP_403_FORBIDDEN
    assert client.post(revoke_url(target.pk)).status_code == status.HTTP_403_FORBIDDEN
    assert client.delete(detail_url(target.pk)).status_code == status.HTTP_403_FORBIDDEN
    target.refresh_from_db()
    assert target.revoked_at is None


@pytest.mark.django_db
def test_old_route_is_gone(client_as, admin_acme):
    assert client_as(admin_acme).get("/api/api-keys/").status_code == status.HTTP_404_NOT_FOUND
