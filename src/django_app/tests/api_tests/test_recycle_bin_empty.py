"""POST /api/recycle-bin/empty/: one request empties every bin the caller may delete in."""

from unittest.mock import patch

import pytest
from rbac.models.enums import Permission, ResourceType
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient
from tables.models import Graph, Secret
from tables.services.recycle_bin.empty_service import EMPTY_ORDER, STORAGE_SOURCE
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.secrets import secret_service
from tests.api_tests.test_secret_use_fk_fields import _client_with_grants
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

EMPTY_URL = "/api/recycle-bin/empty/"
ALL_BITS = int(Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE)


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _client(django_user_model, org, email, grants):
    return _client_with_grants(
        org=org, django_user_model=django_user_model, email=email, resource_permissions=grants
    )


def _binned_flow(org, name="Orders"):
    graph = Graph.objects.create(org=org, name=name)
    graph.delete()
    return graph.pk


def _binned_secret(org, name="api-key"):
    secret = secret_service.create(text="value-for-tests-only", org=org, name=name)
    secret.delete()
    return secret.pk


def test_empty_removes_every_bin_and_never_another_org(admin_client, acme, beta):
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme)
    other_org_flow_id = _binned_flow(beta, name="Theirs")

    response = admin_client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"purged_count": 2, "failed": [], "remaining": 0}
    assert not Graph.all_objects.filter(pk=flow_id).exists()
    assert not Secret.all_objects.filter(pk=secret_id).exists()
    assert Graph.all_objects.filter(pk=other_org_flow_id).exists()


def test_bins_the_caller_cannot_delete_in_are_left_alone(django_user_model, acme):
    client = _client(
        django_user_model,
        acme,
        "empty-flows-only@example.com",
        {ResourceType.FLOWS.value: ALL_BITS, ResourceType.SECRETS.value: int(Permission.READ)},
    )
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["purged_count"] == 1
    assert not Graph.all_objects.filter(pk=flow_id).exists()
    assert Secret.all_objects.filter(pk=secret_id).exists()


def test_a_caller_who_can_delete_nothing_is_refused(django_user_model, acme):
    client = _client(
        django_user_model,
        acme,
        "empty-read-only@example.com",
        {ResourceType.FLOWS.value: int(Permission.READ)},
    )
    flow_id = _binned_flow(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Graph.all_objects.filter(pk=flow_id).exists()


def test_a_failed_item_is_reported_with_its_bin_and_the_rest_go(admin_client, acme):
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme, name="stuck-key")
    real_purge = PurgeService.purge

    def purge(root, *, actor):
        if isinstance(root, Secret):
            raise APIException("This secret can't be deleted right now.")
        return real_purge(root, actor=actor)

    with patch("tables.services.recycle_bin.bulk_service.PurgeService.purge", side_effect=purge):
        response = admin_client.post(EMPTY_URL)

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
    assert set(EMPTY_ORDER) == set(bin_resources()) | {STORAGE_SOURCE}


def test_a_bin_the_caller_can_delete_in_but_not_see_is_left_alone(django_user_model, acme):
    client = _client(
        django_user_model,
        acme,
        "empty-delete-not-read@example.com",
        {
            ResourceType.FLOWS.value: ALL_BITS,
            ResourceType.SECRETS.value: int(Permission.DELETE),
        },
    )
    flow_id, secret_id = _binned_flow(acme), _binned_secret(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not Graph.all_objects.filter(pk=flow_id).exists()
    assert Secret.all_objects.filter(pk=secret_id).exists()


@pytest.mark.parametrize("key_owner", ["user", "system"])
def test_api_keys_cannot_empty_the_bin(key_owner, admin_acme, acme, issue_api_key):
    raw, _ = issue_api_key(user=admin_acme if key_owner == "user" else None)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(acme.id))
    flow_id = _binned_flow(acme)

    response = client.post(EMPTY_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert Graph.all_objects.filter(pk=flow_id).exists()


def test_a_large_bin_is_emptied_over_several_calls(admin_client, acme):
    flow_ids = [_binned_flow(acme, name=f"Flow {number}") for number in range(3)]

    # No time left: each call does one item, then says how many remain.
    with patch("tables.services.recycle_bin.empty_service.EMPTY_TIME_BUDGET_SECONDS", 0):
        answers = [admin_client.post(EMPTY_URL).json() for _ in range(3)]

    assert [(a["purged_count"], a["remaining"]) for a in answers] == [(1, 2), (1, 1), (1, 0)]
    assert not Graph.all_objects.filter(pk__in=flow_ids).exists()

