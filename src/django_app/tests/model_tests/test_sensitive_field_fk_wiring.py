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
    return Organization.objects.create(name="Org FKWiring")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_fkwiring@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
def test_llm_config_has_nullable_api_key_secret_fk(org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    config = LLMConfig.objects.create(org=org, custom_name="cfg", model=model)
    assert config.api_key_secret_id is None


@pytest.mark.django_db
def test_deleting_referenced_secret_nulls_the_fk_not_the_config(admin_client, org):
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None, org=org)
    secret = Secret(org=org, name="fk-wiring-test-key")
    secret_encryption.encrypt(text="sk-live-abc123").write_to(secret)
    secret.save()
    config = LLMConfig.objects.create(
        org=org, custom_name="cfg", model=model, api_key_secret=secret
    )

    resp = admin_client.delete(f"/api/secrets/{secret.id}/")
    assert resp.status_code == 204

    config.refresh_from_db()
    assert config.api_key_secret_id is None
    assert LLMConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_embedding_config_and_mcp_tool_also_have_nullable_secret_fk(org):
    embed_model = EmbeddingModel.objects.create(name="text-embedding-3", org=org)
    embedding_config = EmbeddingConfig.objects.create(
        org=org, custom_name="embed-cfg", model=embed_model
    )
    assert embedding_config.api_key_secret_id is None

    tool = McpTool.objects.create(
        org=org, name="tool", transport="https://example.com", tool_name="t"
    )
    assert tool.auth_secret_id is None
