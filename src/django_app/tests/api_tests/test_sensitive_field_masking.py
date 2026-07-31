import pytest
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.mcp_models import McpTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_encryption, secret_service


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
def test_llm_config_attaches_secret_by_id(client_a, org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    secret = secret_service.create(text="sk-live-abc123", org=org, name="llm-key")

    create_resp = client_a.post(
        "/api/llm-configs/",
        {
            "custom_name": "cfg",
            "model": model.id,
            "api_key_secret_id": secret.id,
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.content
    assert create_resp.data["api_key_secret_id"] == secret.id

    # The old plaintext field is gone from the contract entirely.
    assert "api_key" not in create_resp.data
    assert "api_key_secret" not in create_resp.data

    config = LLMConfig.objects.get(id=create_resp.data["id"])
    assert config.api_key_secret_id == secret.id
    # No new Secret was created — the existing row was reused.
    assert Secret.objects.filter(org=org).count() == 1


@pytest.mark.django_db
def test_llm_config_swaps_and_detaches_secret(client_a, org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    first = secret_service.create(text="sk-first", org=org, name="first-key")
    second = secret_service.create(text="sk-second", org=org, name="second-key")
    config = LLMConfig.objects.create(
        custom_name="cfg", model=model, org=org, api_key_secret=first
    )

    swap = client_a.patch(
        f"/api/llm-configs/{config.id}/",
        {"api_key_secret_id": second.id},
        format="json",
    )
    assert swap.status_code == 200, swap.content
    config.refresh_from_db()
    assert config.api_key_secret_id == second.id
    # Swapping must not mutate or delete the secret being swapped away from.
    first.refresh_from_db()
    assert secret_encryption.decrypt(encryptedtext=first.value) == "sk-first"

    detach = client_a.patch(
        f"/api/llm-configs/{config.id}/",
        {"api_key_secret_id": None},
        format="json",
    )
    assert detach.status_code == 200, detach.content
    config.refresh_from_db()
    assert config.api_key_secret_id is None
    # Detaching leaves both Secret rows intact.
    assert Secret.objects.filter(id__in=[first.id, second.id]).count() == 2


@pytest.mark.django_db
def test_omitting_the_field_leaves_the_existing_secret_attached(client_a, org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    secret = secret_service.create(text="sk-keep", org=org, name="keep-key")
    config = LLMConfig.objects.create(
        custom_name="cfg", model=model, org=org, api_key_secret=secret
    )

    resp = client_a.patch(
        f"/api/llm-configs/{config.id}/", {"custom_name": "renamed"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    config.refresh_from_db()
    assert config.custom_name == "renamed"
    assert config.api_key_secret_id == secret.id


@pytest.mark.django_db
def test_plaintext_api_key_is_no_longer_accepted(client_a, org):
    """The old contract is gone: DRF ignores the unknown key, so the config is
    created with no credential rather than half-configured."""
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)

    resp = client_a.post(
        "/api/llm-configs/",
        {"custom_name": "cfg", "model": model.id, "api_key": "sk-live-abc123"},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    config = LLMConfig.objects.get(id=resp.data["id"])
    assert config.api_key_secret_id is None
    assert not Secret.objects.filter(org=org).exists()


@pytest.mark.django_db
def test_embedding_config_attaches_secret_by_id(client_a, org):
    model = EmbeddingModel.objects.create(name="text-embedding-3", org=org)
    secret = secret_service.create(text="sk-embed-abc123", org=org, name="embed-key")

    resp = client_a.post(
        "/api/embedding-configs/",
        {
            "custom_name": "embed-cfg",
            "model": model.id,
            "api_key_secret_id": secret.id,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.data["api_key_secret_id"] == secret.id
    assert "api_key" not in resp.data

    config = EmbeddingConfig.objects.get(id=resp.data["id"])
    assert config.api_key_secret_id == secret.id


@pytest.mark.django_db
def test_mcp_tool_attaches_secret_by_id(client_a, org):
    secret = secret_service.create(text="Bearer sk-mcp-abc123", org=org, name="mcp-key")

    resp = client_a.post(
        "/api/mcp-tools/",
        {
            "name": "tool-a",
            "transport": "https://example.com/sse",
            "tool_name": "search",
            "auth_secret_id": secret.id,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.data["auth_secret_id"] == secret.id
    assert "auth" not in resp.data

    tool = McpTool.objects.get(id=resp.data["id"])
    assert tool.auth_secret_id == secret.id
