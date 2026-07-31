import pytest
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service


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
def test_telegram_bot_api_key_attaches_secret_by_id(client_a, graph, org):
    secret = secret_service.create(
        text="bot-token-abc123", org=org, name="telegram-bot-key"
    )

    create_resp = client_a.post(
        "/api/telegram-trigger-nodes/",
        {
            "node_name": "telegram-1",
            "graph": graph.id,
            "telegram_bot_api_key_secret_id": secret.id,
            "fields": [],
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.content
    assert create_resp.data["telegram_bot_api_key_secret_id"] == secret.id
    assert "telegram_bot_api_key" not in create_resp.data

    node = TelegramTriggerNode.objects.get(id=create_resp.data["id"])
    assert node.telegram_bot_api_key_secret_id == secret.id
    # Reused the existing row rather than creating a second one.
    assert Secret.objects.filter(org=org).count() == 1


@pytest.mark.django_db
def test_telegram_node_created_without_a_secret(client_a, graph):
    resp = client_a.post(
        "/api/telegram-trigger-nodes/",
        {"node_name": "telegram-2", "graph": graph.id, "fields": []},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    node = TelegramTriggerNode.objects.get(id=resp.data["id"])
    assert node.telegram_bot_api_key_secret_id is None
