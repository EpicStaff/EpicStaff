import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import ApiKey, OrganizationUser
from tables.services.rbac.api_key.generator import ApiKeyGenerator

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
    user = django_user_model.objects.create_user(
        email="acme-keyholder@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_anonymous_401():
    assert APIClient().get(LIST_URL).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_denied_without_api_keys_read(client_as, member_only):
    assert client_as(member_only).get(LIST_URL).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_returns_paginated_envelope(client_as, admin_acme, acme_member, acme, make_key):
    make_key(acme_member, name="laptop")

    body = client_as(admin_acme).get(LIST_URL).json()

    assert set(body.keys()) == {"count", "next", "previous", "results"}
    row = body["results"][0]
    assert row["name"] == "laptop"
    assert row["owner"]["email"] == "acme-keyholder@example.com"
    assert row["org_ids"] == [acme.id]
    assert "key_hash" not in row


@pytest.mark.django_db
def test_no_org_header_is_required(client_as, admin_acme, acme_member, make_key):
    make_key(acme_member, name="headerless")

    assert client_as(admin_acme).get(LIST_URL).status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_forbidden_org_ids_403(client_as, admin_acme, beta):
    resp = client_as(admin_acme).get(LIST_URL, {"org_ids": str(beta.id)})

    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_bad_status_filter_400(client_as, admin_acme):
    resp = client_as(admin_acme).get(LIST_URL, {"status": "bogus"})

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid"


@pytest.mark.django_db
def test_bad_user_filter_400(client_as, admin_acme):
    resp = client_as(admin_acme).get(LIST_URL, {"user": "abc"})

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid"


@pytest.mark.django_db
def test_superadmin_owned_keys_are_hidden_from_delegated_admins(
    client_as, admin_acme, superadmin, acme, role_org_admin, make_key
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    make_key(superadmin, name="platform")

    names = [r["name"] for r in client_as(admin_acme).get(LIST_URL).json()["results"]]

    assert "platform" not in names


@pytest.mark.django_db
def test_delegated_admin_gets_404_on_a_superadmin_key(
    client_as, admin_acme, superadmin, acme, role_org_admin, make_key
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    key = make_key(superadmin, name="platform")

    resp = client_as(admin_acme).post(revoke_url(key.pk))

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "api_key_not_found"


@pytest.mark.django_db
def test_superadmin_can_revoke_a_superadmin_key(
    client_as, superadmin, django_user_model, make_key
):
    peer = django_user_model.objects.create_user(
        email="peer-platform@example.com",
        password="StrongPass123!",
        is_superadmin=True,
    )
    key = make_key(peer, name="peer")

    resp = client_as(superadmin).post(revoke_url(key.pk))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "revoked"


@pytest.mark.django_db
def test_revoke_and_delete(client_as, admin_acme, acme_member, make_key):
    key = make_key(acme_member, name="target")
    client = client_as(admin_acme)

    assert client.post(revoke_url(key.pk)).status_code == status.HTTP_200_OK
    assert client.delete(detail_url(key.pk)).status_code == status.HTTP_204_NO_CONTENT
    assert not ApiKey.objects.filter(pk=key.pk).exists()


@pytest.mark.django_db
def test_revoke_response_carries_org_ids(
    client_as, admin_acme, acme_member, acme, make_key
):
    key = make_key(acme_member, name="revoked-row")

    body = client_as(admin_acme).post(revoke_url(key.pk)).json()

    assert body["status"] == "revoked"
    assert body["org_ids"] == [acme.id]


@pytest.mark.django_db
def test_cross_org_key_is_404(
    client_as, admin_acme, django_user_model, beta, role_member, make_key
):
    outsider = django_user_model.objects.create_user(
        email="far-away@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_member)
    key = make_key(outsider, name="far")

    assert (
        client_as(admin_acme).delete(detail_url(key.pk)).status_code
        == status.HTTP_404_NOT_FOUND
    )


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


@pytest.mark.django_db
def test_old_route_is_gone(client_as, admin_acme):
    assert (
        client_as(admin_acme).get("/api/api-keys/").status_code
        == status.HTTP_404_NOT_FOUND
    )
