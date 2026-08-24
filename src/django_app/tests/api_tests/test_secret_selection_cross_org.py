"""A secret belonging to another organization must be unusable — rejected
identically to a nonexistent id, revealing nothing about its existence.

This is the guard that makes secret-selection-by-id safe. Without the
org-scoped field class, DRF would happily attach any org's secret.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import LLMConfig, McpTool, Secret
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import (
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A CrossOrg")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B CrossOrg")


@pytest.fixture
def client_a(db, django_user_model, org_a):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_crossorg@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def foreign_secret(org_b):
    """A secret org A must never be able to reach."""
    return secret_service.create(text="sk-org-b-private", org=org_b, name="b-key")


@pytest.mark.django_db
def test_llm_config_rejects_foreign_secret(client_a, org_a, foreign_secret):
    model = LLMModel.objects.create(name="gpt-4o-xorg", llm_provider=None, org=org_a)

    resp = client_a.post(
        "/api/llm-configs/",
        {
            "custom_name": "cfg-xorg",
            "model": model.id,
            "api_key_secret_id": foreign_secret.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    # This project's exception handler flattens ValidationError into
    # {"code", "message", "status_code"}, so the field name lives in "message".
    assert "api_key_secret_id" in resp.data["message"]
    assert "does not exist" in resp.data["message"]
    assert not LLMConfig.objects.filter(custom_name="cfg-xorg").exists()


@pytest.mark.django_db
def test_rejection_is_indistinguishable_from_a_nonexistent_id(
    client_a, org_a, foreign_secret
):
    """Existence in another org must not be revealed: the error for a foreign
    secret must match the error for an id that does not exist at all."""
    model = LLMModel.objects.create(name="gpt-4o-xorg2", llm_provider=None, org=org_a)
    missing_id = Secret.objects.order_by("-pk").first().pk + 1000

    foreign = client_a.post(
        "/api/llm-configs/",
        {
            "custom_name": "cfg-f",
            "model": model.id,
            "api_key_secret_id": foreign_secret.id,
        },
        format="json",
    )
    nonexistent = client_a.post(
        "/api/llm-configs/",
        {
            "custom_name": "cfg-n",
            "model": model.id,
            "api_key_secret_id": missing_id,
        },
        format="json",
    )

    assert foreign.status_code == nonexistent.status_code == 400

    # Compare the messages with the offending pk removed, since DRF interpolates
    # it. Identical status with differing detail is exactly the leak this guards.
    def _without_digits(detail):
        return "".join(ch for ch in str(detail) if not ch.isdigit())

    assert _without_digits(foreign.data["message"]) == _without_digits(
        nonexistent.data["message"]
    )


@pytest.mark.django_db
def test_patch_cannot_swap_in_a_foreign_secret(client_a, org_a, foreign_secret):
    model = LLMModel.objects.create(name="gpt-4o-xorg3", llm_provider=None, org=org_a)
    own = secret_service.create(text="sk-mine", org=org_a, name="a-key")
    config = LLMConfig.objects.create(
        custom_name="cfg-patch", model=model, org=org_a, api_key_secret=own
    )

    resp = client_a.patch(
        f"/api/llm-configs/{config.id}/",
        {"api_key_secret_id": foreign_secret.id},
        format="json",
    )

    assert resp.status_code == 400, resp.content
    config.refresh_from_db()
    assert config.api_key_secret_id == own.id


@pytest.mark.django_db
def test_embedding_config_rejects_foreign_secret(client_a, org_a, foreign_secret):
    model = EmbeddingModel.objects.create(name="embed-xorg", org=org_a)

    resp = client_a.post(
        "/api/embedding-configs/",
        {
            "custom_name": "embed-xorg",
            "model": model.id,
            "api_key_secret_id": foreign_secret.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert not EmbeddingConfig.objects.filter(custom_name="embed-xorg").exists()


@pytest.mark.django_db
def test_mcp_tool_rejects_foreign_secret(client_a, foreign_secret):
    resp = client_a.post(
        "/api/mcp-tools/",
        {
            "name": "tool-xorg",
            "transport": "https://example.com/sse",
            "tool_name": "search",
            "auth_secret_id": foreign_secret.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert not McpTool.objects.filter(name="tool-xorg").exists()


@pytest.mark.django_db
def test_realtime_config_rejects_foreign_secret(client_a, org_a, foreign_secret):
    model = RealtimeModel.objects.create(name="gpt-4o-realtime-xorg", org=org_a)

    resp = client_a.post(
        "/api/realtime-model-configs/",
        {
            "custom_name": "rt-xorg",
            "realtime_model": model.id,
            "api_key_secret_id": foreign_secret.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert not RealtimeConfig.objects.filter(custom_name="rt-xorg").exists()


@pytest.mark.django_db
def test_realtime_transcription_config_rejects_foreign_secret(
    client_a, org_a, foreign_secret
):
    model = RealtimeTranscriptionModel.objects.create(name="whisper-xorg", org=org_a)

    resp = client_a.post(
        "/api/realtime-transcription-model-configs/",
        {
            "custom_name": "rtt-xorg",
            "realtime_transcription_model": model.id,
            "api_key_secret_id": foreign_secret.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert not RealtimeTranscriptionConfig.objects.filter(
        custom_name="rtt-xorg"
    ).exists()


@pytest.mark.django_db
def test_telegram_trigger_node_rejects_foreign_secret(client_a, org_a, foreign_secret):
    graph = Graph.objects.create(name="tg-xorg-graph", org=org_a)

    resp = client_a.post(
        "/api/telegram-trigger-nodes/",
        {
            "node_name": "tg-xorg",
            "graph": graph.id,
            "telegram_bot_api_key_secret_id": foreign_secret.id,
            "fields": [],
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert not TelegramTriggerNode.objects.filter(node_name="tg-xorg").exists()
