import pytest
from rest_framework.test import APIClient

from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_encryption


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org TelegramSecret")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="telegram-secret-graph", org=org)


@pytest.fixture
def client_a(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_telegram_secret@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
def test_telegram_bot_api_key_masked_round_trip(client_a, graph):
    create_resp = client_a.post(
        "/api/telegram-trigger-nodes/",
        {
            "node_name": "telegram-1",
            "graph": graph.id,
            "telegram_bot_api_key": "bot-token-abc123",
            "fields": [],
        },
        format="json",
    )
    assert create_resp.status_code == 201
    assert create_resp.data["telegram_bot_api_key"] == "****c123"

    node = TelegramTriggerNode.objects.get(id=create_resp.data["id"])
    assert node.telegram_bot_api_key_secret is not None
    assert node.telegram_bot_api_key_secret.org_id == graph.org_id
    assert (
        secret_encryption.decrypt(encryptedtext=node.telegram_bot_api_key_secret.value)
        == "bot-token-abc123"
    )
