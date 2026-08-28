import pytest

from tables.models import (
    EmbeddingConfig,
    EmbeddingModel,
    LLMConfig,
    LLMModel,
    McpTool,
    Provider,
)
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ConverterIds")


@pytest.fixture
def converter():
    return ConverterService()


@pytest.mark.django_db
class TestConverterEmitsIdsNotPlaintext:
    def test_llm_config_carries_id_and_empty_slot(self, org, converter):
        provider, _ = Provider.objects.get_or_create(name="openai")
        model = LLMModel.objects.create(name="gpt-4o-conv-id", llm_provider=provider)
        secret = secret_service.create(
            text="sk-llm-must-not-be-in-payload", org=org, name="conv-llm"
        )
        config = LLMConfig.objects.create(
            custom_name="conv-llm-cfg", model=model, org=org, api_key_secret=secret
        )

        data = converter.convert_llm_config_to_pydantic(config)

        assert data.config.api_key_secret_id == secret.pk
        assert data.config.api_key is None

    def test_embedding_config_carries_id_and_empty_slot(self, org, converter):
        # EmbedderData.provider is a required str, so the model needs a provider.
        provider, _ = Provider.objects.get_or_create(name="openai")
        model = EmbeddingModel.objects.create(
            name="text-embedding-conv-id", embedding_provider=provider
        )
        secret = secret_service.create(
            text="sk-embed-must-not-be-in-payload", org=org, name="conv-embed"
        )
        config = EmbeddingConfig.objects.create(
            custom_name="conv-embed-cfg", model=model, org=org, api_key_secret=secret
        )

        data = converter.convert_embedding_config_to_pydantic(embedding_config=config)

        assert data.config.api_key_secret_id == secret.pk
        assert data.config.api_key is None

    def test_mcp_tool_carries_id_and_empty_slot(self, org, converter):
        secret = secret_service.create(
            text="mcp-token-must-not-be-in-payload", org=org, name="conv-mcp"
        )
        tool = McpTool.objects.create(
            transport="https://mcp.example.test/sse",
            tool_name="conv-mcp-tool",
            org=org,
            auth_secret=secret,
        )

        data = converter.convert_mcp_tool_to_pydantic(tool)

        assert data.auth_secret_id == secret.pk
        assert data.auth is None

    def test_null_fk_yields_null_carrier(self, org, converter):
        provider, _ = Provider.objects.get_or_create(name="openai")
        model = LLMModel.objects.create(name="gpt-4o-conv-nokey", llm_provider=provider)
        config = LLMConfig.objects.create(
            custom_name="conv-no-key", model=model, org=org
        )

        data = converter.convert_llm_config_to_pydantic(config)

        assert data.config.api_key_secret_id is None
        assert data.config.api_key is None
