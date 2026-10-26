"""A config whose provider was deleted fails conversion with an error naming the config."""

import pytest

from rbac.models import Organization
from tables.exceptions import ConfigProviderMissingError
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.services.converter_service import ConverterService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="MissingProvider Org")


@pytest.fixture
def provider(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    return provider


@pytest.mark.django_db
class TestEmbeddingConfigMissingProvider:
    def test_provider_deleted_raises_naming_config(self, org, provider):
        model = EmbeddingModel.objects.create(name="emb", org=org, embedding_provider=provider)
        config = EmbeddingConfig.objects.create(custom_name="Docs embedder", model=model, org=org)
        provider.delete()
        config = EmbeddingConfig.objects.select_related("model__embedding_provider").get(
            pk=config.pk
        )

        with pytest.raises(ConfigProviderMissingError) as error_info:
            ConverterService().convert_embedding_config_to_pydantic(config)

        assert error_info.value.status_code == 400
        assert "Embedding config 'Docs embedder' has no model or provider" in str(error_info.value.detail)

    def test_model_deleted_raises_naming_config(self, org):
        config = EmbeddingConfig.objects.create(custom_name="Orphan embedder", model=None, org=org)

        with pytest.raises(ConfigProviderMissingError) as error_info:
            ConverterService().convert_embedding_config_to_pydantic(config)

        assert "Embedding config 'Orphan embedder'" in str(error_info.value.detail)

    def test_provider_present_converts(self, org, provider):
        model = EmbeddingModel.objects.create(name="emb", org=org, embedding_provider=provider)
        config = EmbeddingConfig.objects.create(custom_name="ok", model=model, org=org)

        data = ConverterService().convert_embedding_config_to_pydantic(config)

        assert data.provider == "openai"
        assert data.config.model == "emb"


@pytest.mark.django_db
class TestLLMConfigMissingProvider:
    def test_provider_deleted_raises_naming_config(self, org, provider):
        model = LLMModel.objects.create(name="llm", org=org, llm_provider=provider)
        config = LLMConfig.objects.create(custom_name="Main LLM", model=model, org=org)
        provider.delete()
        config = LLMConfig.objects.select_related("model__llm_provider").get(pk=config.pk)

        with pytest.raises(ConfigProviderMissingError) as error_info:
            ConverterService().convert_llm_config_to_pydantic(config)

        assert error_info.value.status_code == 400
        assert "LLM config 'Main LLM' has no model or provider" in str(error_info.value.detail)

    def test_config_without_model_still_returns_none(self, org):
        config = LLMConfig.objects.create(custom_name="no model", model=None, org=org)

        assert ConverterService().convert_llm_config_to_pydantic(config) is None

    def test_none_config_still_returns_none(self):
        assert ConverterService().convert_llm_config_to_pydantic(None) is None

    def test_provider_present_converts(self, org, provider):
        model = LLMModel.objects.create(name="llm", org=org, llm_provider=provider)
        config = LLMConfig.objects.create(custom_name="ok", model=model, org=org)

        data = ConverterService().convert_llm_config_to_pydantic(config)

        assert data.provider == "openai"
        assert data.config.model == "llm"


@pytest.fixture
def cdt_node(org):
    from tables.models import ClassificationDecisionTableNode, Graph

    graph = Graph.objects.create(name="cdt-missing-provider", org=org)
    return ClassificationDecisionTableNode.objects.create(graph=graph)


@pytest.mark.django_db
class TestClassificationDecisionTableMissingProvider:
    def _convert(self, node):
        from utils.graph_utils import NodeNameResolver

        node = type(node).objects.get(pk=node.pk)
        return ConverterService().convert_classification_decision_table_node_to_pydantic(
            node, resolver=NodeNameResolver(graph_id=node.graph_id), graph_id=node.graph_id
        )

    def _config(self, org, name, provider):
        model = LLMModel.objects.create(name=f"model-{name}", org=org, llm_provider=provider)
        return LLMConfig.objects.create(custom_name=name, model=model, org=org)

    def test_prompt_falling_back_to_default_config_with_deleted_provider_raises(
        self, org, cdt_node
    ):
        from tables.models import ClassificationDecisionTablePrompt

        doomed_provider = Provider.objects.create(name="doomed-provider")
        cdt_node.default_llm_config = self._config(org, "Default LLM", doomed_provider)
        cdt_node.save()
        ClassificationDecisionTablePrompt.objects.create(cdt_node=cdt_node, prompt_key="p1")
        doomed_provider.delete()

        with pytest.raises(ConfigProviderMissingError) as error_info:
            self._convert(cdt_node)

        assert "LLM config 'Default LLM'" in str(error_info.value.detail)

    def test_prompt_with_own_valid_config_ignores_default_with_deleted_provider(
        self, org, provider, cdt_node
    ):
        from tables.models import ClassificationDecisionTablePrompt

        doomed_provider = Provider.objects.create(name="doomed-provider")
        cdt_node.default_llm_config = self._config(org, "Default LLM", doomed_provider)
        cdt_node.save()
        ClassificationDecisionTablePrompt.objects.create(
            cdt_node=cdt_node,
            prompt_key="p1",
            llm_config=self._config(org, "Own LLM", provider),
        )
        doomed_provider.delete()

        data = self._convert(cdt_node)

        assert data.prompts["p1"].llm_data.provider == "openai"
