"""API tests for the System One config bulk delete: the route exists, is permission-gated and org-scoped."""

import pytest

from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from tables.models import SystemOneConfig
from tests.api_tests.bulk_delete_helpers import custom_role_client, org_admin_client

ROUTE = "/api/system-one-configs/bulk-delete/"


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.mark.django_db
def test_bulk_delete_route_deletes_a_config(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    config = SystemOneConfig.objects.create(org=org_a, custom_name="cfg", provider="llm")

    resp = client.post(ROUTE, {"ids": [config.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [config.id]
    assert resp.data["deleted_count"] == 1
    assert not SystemOneConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_bulk_delete_requires_delete_permission(django_user_model, org_a):
    client = custom_role_client(
        django_user_model,
        org_a,
        "reader@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    config = SystemOneConfig.objects.create(org=org_a, custom_name="cfg", provider="llm")

    resp = client.post(ROUTE, {"ids": [config.id]}, format="json")

    assert resp.status_code == 403
    assert SystemOneConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_bulk_delete_another_orgs_config_is_not_found(django_user_model, org_a, org_b):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    other = SystemOneConfig.objects.create(org=org_b, custom_name="other", provider="llm")

    resp = client.post(ROUTE, {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert SystemOneConfig.objects.filter(id=other.id).exists()
