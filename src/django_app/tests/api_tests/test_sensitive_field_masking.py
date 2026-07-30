import pytest
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.mcp_models import McpTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_encryption


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Masking")


@pytest.fixture
def client_a(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_masking@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
def test_llm_config_api_key_masked_round_trip(client_a, org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    create_resp = client_a.post(
        "/api/llm-configs/",
        {"custom_name": "cfg", "model": model.id, "api_key": "sk-live-abc123"},
        format="json",
    )
    assert create_resp.status_code == 201
    assert create_resp.data["api_key"] == "****c123"
    assert (
        "api_key_secret" not in create_resp.data
    )  # Meta.exclude suppressed the duplicate

    config = LLMConfig.objects.get(id=create_resp.data["id"])
    secret = config.api_key_secret
    assert secret is not None
    assert secret.org_id == org.id
    assert secret_encryption.decrypt(encryptedtext=secret.value) == "sk-live-abc123"

    # PUT echoing the mask back leaves the secret untouched.
    put_resp = client_a.put(
        f"/api/llm-configs/{config.id}/",
        {"custom_name": "cfg", "model": model.id, "api_key": "****c123"},
        format="json",
    )
    assert put_resp.status_code == 200
    config.refresh_from_db()
    assert config.api_key_secret_id == secret.id

    # A real new value rotates the SAME Secret row in place.
    patch_resp = client_a.patch(
        f"/api/llm-configs/{config.id}/", {"api_key": "sk-live-newvalue"}, format="json"
    )
    assert patch_resp.status_code == 200
    config.refresh_from_db()
    assert config.api_key_secret_id == secret.id  # same row, rotated
    secret.refresh_from_db()
    assert secret_encryption.decrypt(encryptedtext=secret.value) == "sk-live-newvalue"

    # Clearing detaches the FK without deleting the Secret row.
    clear_resp = client_a.patch(
        f"/api/llm-configs/{config.id}/", {"api_key": None}, format="json"
    )
    assert clear_resp.status_code == 200
    config.refresh_from_db()
    assert config.api_key_secret_id is None
    assert Secret.objects.filter(id=secret.id).exists()


@pytest.mark.django_db
def test_embedding_config_api_key_masked_on_create(client_a, org):
    model = EmbeddingModel.objects.create(name="text-embedding-3", org=org)
    resp = client_a.post(
        "/api/embedding-configs/",
        {"custom_name": "embed-cfg", "model": model.id, "api_key": "sk-embed-abc123"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["api_key"] == "****c123"
    config = EmbeddingConfig.objects.get(id=resp.data["id"])
    assert (
        secret_encryption.decrypt(encryptedtext=config.api_key_secret.value)
        == "sk-embed-abc123"
    )


@pytest.mark.django_db
def test_mcp_tool_auth_masked_on_create(client_a, org):
    resp = client_a.post(
        "/api/mcp-tools/",
        {
            "name": "tool-a",
            "transport": "https://example.com/sse",
            "tool_name": "search",
            "auth": "Bearer sk-mcp-abc123",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["auth"] == "****c123"
    tool = McpTool.objects.get(id=resp.data["id"])
    assert (
        secret_encryption.decrypt(encryptedtext=tool.auth_secret.value)
        == "Bearer sk-mcp-abc123"
    )
