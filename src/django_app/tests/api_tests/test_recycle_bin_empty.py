"""POST /api/recycle-bin/empty/: one request empties every bin of the active org. Superadmin only."""

from unittest.mock import patch

import pytest
from rbac.access.gates import DenyApiKeyAuth, IsSuperadmin
from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient
from tables.models import Graph, Secret
from tables.services.recycle_bin.empty_service import EMPTY_ORDER
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.secrets import secret_service
from tests.api_tests.test_secret_use_fk_fields import _client_with_grants
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

EMPTY_URL = "/api/recycle-bin/empty/"
ALL_BITS = int(Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE)


def _client_in(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    return _client_in(client_as, admin_acme, acme)


def _binned_flow(org, name="Orders"):
    graph = Graph.objects.create(org=org, name=name)
    graph.delete()
    return graph.pk


def _binned_secret(org, name="api-key"):
    secret = secret_service.create(text="value-for-tests-only", org=org, name=name)
    secret.delete()
    return secret.pk


def test_empty_removes_every_bin_and_never_another_org(superadmin_in_acme, acme, beta):
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme)
    other_org_flow_id = _binned_flow(beta, name="Theirs")

    response = superadmin_in_acme.post(EMPTY_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"purged_count": 2, "failed": [], "remaining": 0}
    assert not Graph.all_objects.filter(pk=flow_id).exists()
    assert not Secret.all_objects.filter(pk=secret_id).exists()
    assert Graph.all_objects.filter(pk=other_org_flow_id).exists()


def test_an_org_admin_cannot_empty_the_bin(admin_client, acme):
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme)

    response = admin_client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.json()["message"] == IsSuperadmin.message
    assert Graph.deleted_objects.filter(pk=flow_id).exists()
    assert Secret.deleted_objects.filter(pk=secret_id).exists()


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_a_member_or_viewer_cannot_empty_the_bin(
    role, client_as, django_user_model, acme, role_member, role_viewer
):
    user = django_user_model.objects.create_user(email=f"empty-{role}@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=acme, role=role_member if role == "member" else role_viewer)
    flow_id = _binned_flow(acme)

    response = _client_in(client_as, user, acme).post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.json()["message"] == IsSuperadmin.message
    assert Graph.deleted_objects.filter(pk=flow_id).exists()


def test_a_role_holding_every_bit_cannot_empty_the_bin(django_user_model, acme):
    client = _client_with_grants(
        org=acme,
        django_user_model=django_user_model,
        email="empty-all-bits@example.com",
        resource_permissions={ResourceType.FLOWS.value: ALL_BITS},
    )
    flow_id = _binned_flow(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.json()["message"] == IsSuperadmin.message
    assert Graph.deleted_objects.filter(pk=flow_id).exists()


def test_a_superadmin_without_an_active_org_is_400_and_nothing_goes(client_as, superadmin, acme, beta):
    flow_ids = [_binned_flow(acme), _binned_flow(beta, name="Theirs")]

    response = client_as(superadmin).post(EMPTY_URL)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json()["code"] == "org_context_required"
    assert Graph.deleted_objects.filter(pk__in=flow_ids).count() == 2


def test_a_superadmin_cannot_empty_an_inactive_orgs_bin(client_as, superadmin, acme):
    flow_id = _binned_flow(acme)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    response = _client_in(client_as, superadmin, acme).post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Graph.deleted_objects.filter(pk=flow_id).exists()


def test_anonymous_gets_401(acme):
    client = APIClient()
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    flow_id = _binned_flow(acme)

    assert client.post(EMPTY_URL).status_code == status.HTTP_401_UNAUTHORIZED
    assert Graph.deleted_objects.filter(pk=flow_id).exists()


def test_a_failed_item_is_reported_with_its_bin_and_the_rest_go(superadmin_in_acme, acme):
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme, name="stuck-key")
    real_purge = PurgeService.purge

    def purge(root, *, actor):
        if isinstance(root, Secret):
            raise APIException("This secret can't be deleted right now.")
        return real_purge(root, actor=actor)

    with patch("tables.services.recycle_bin.bulk_service.PurgeService.purge", side_effect=purge):
        response = superadmin_in_acme.post(EMPTY_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {
        "purged_count": 1,
        "failed": [
            {
                "source": "secret",
                "id": secret_id,
                "name": "stuck-key",
                "message": "This secret can't be deleted right now.",
            }
        ],
        # The failed secret is still in the bin.
        "remaining": 1,
    }
    assert not Graph.all_objects.filter(pk=flow_id).exists()
    assert Secret.all_objects.filter(pk=secret_id).exists()


def test_empty_names_every_bin_the_registry_has():
    assert set(EMPTY_ORDER) == set(bin_resources()) | {RecycleBinSource.STORAGE}


@pytest.mark.parametrize("key_owner", ["org_admin", "superadmin", "system"])
def test_api_keys_cannot_empty_the_bin(key_owner, admin_acme, superadmin, acme, issue_api_key):
    owners = {"org_admin": admin_acme, "superadmin": superadmin, "system": None}
    raw, _ = issue_api_key(user=owners[key_owner])
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(acme.id))
    flow_id = _binned_flow(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.json()["message"] == DenyApiKeyAuth.message
    assert Graph.all_objects.filter(pk=flow_id).exists()


def test_a_large_bin_is_emptied_over_several_calls(superadmin_in_acme, acme):
    flow_ids = [_binned_flow(acme, name=f"Flow {number}") for number in range(3)]

    # No time left: each call does one item, then says how many remain.
    with patch("tables.services.recycle_bin.empty_service.EMPTY_TIME_BUDGET_SECONDS", 0):
        answers = [superadmin_in_acme.post(EMPTY_URL).json() for _ in range(3)]

    assert [(a["purged_count"], a["remaining"]) for a in answers] == [(1, 2), (1, 1), (1, 0)]
    assert not Graph.all_objects.filter(pk__in=flow_ids).exists()
