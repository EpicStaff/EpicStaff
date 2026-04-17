from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.config.models.language_model_config import LanguageModelConfig
from graphrag.config.models.chunking_config import ChunkingConfig
from graphrag.config.models.input_config import InputConfig
from graphrag.config.models.storage_config import StorageConfig
from graphrag.config.models.extract_graph_config import ExtractGraphConfig
from graphrag.config.models.cluster_graph_config import ClusterGraphConfig

from graphrag.config.models.text_embedding_config import TextEmbeddingConfig
from graphrag.config.enums import (
    ModelType,
    StorageType,
    InputFileType,
    ChunkStrategyType,
)
from src.shared.models import GraphRagBasicSearchParams, GraphRagLocalSearchParams
from rag.graph_rag.utils import (
    build_basic_search_prompt,
    build_local_search_prompt,
)


# Model ID constants used by GraphRagConfig
DEFAULT_CHAT_MODEL_ID = "default_chat_model"
DEFAULT_EMBEDDING_MODEL_ID = "default_embedding_model"


class GraphRagConfigBuilder:
    """
    Builds GraphRagConfig from database configurations.

    This class creates programmatic GraphRagConfig instances instead of
    loading from YAML files, allowing us to use database-stored settings.
    """

    def __init__(self):
        """Initialize the config builder."""
        pass

    def build_config(
        self,
        root_folder: Path,
        llm_config: Dict[str, Any],
        embedder_config: Dict[str, Any],
        index_config: Optional[Dict[str, Any]] = None,
    ) -> GraphRagConfig:
        """
        Build a complete GraphRagConfig from database settings.

        Args:
            root_folder: Root folder for the GraphRag (contains input/, output/, etc.)
            llm_config: LLM configuration dict from storage.get_llm_configuration()
            embedder_config: Embedder configuration dict from storage.get_embedder_configuration()
            index_config: Optional index config dict from storage.get_index_config_dict()

        Returns:
            GraphRagConfig instance ready for indexing/searching
        """
        root_dir = str(root_folder)

        models = self._build_models_dict(llm_config, embedder_config)

        chunks = self._build_chunking_config(index_config)

        input_config = self._build_input_config(index_config)

        output_config = self._build_output_config(root_folder)

        extract_graph = self._build_extract_graph_config(index_config)

        cluster_graph = self._build_cluster_graph_config(index_config)

        embed_text = self._build_text_embedding_config()

        config = GraphRagConfig(
            root_dir=root_dir,
            models=models,
            chunks=chunks,
            input=input_config,
            output=output_config,
            extract_graph=extract_graph,
            cluster_graph=cluster_graph,
            embed_text=embed_text,
        )

        logger.info(f"Built GraphRagConfig for root_dir: {root_dir}")
        return config

    def _build_models_dict(
        self,
        llm_config: Dict[str, Any],
        embedder_config: Dict[str, Any],
    ) -> Dict[str, LanguageModelConfig]:
        """
        Build the models dictionary with llm and embedding model configs.
        """
        models = {}

        # Build llm model config
        chat_model = self._build_language_model_config(
            config=llm_config,
            is_embedding=False,
        )
        models[DEFAULT_CHAT_MODEL_ID] = chat_model

        # Build embedding model config
        embedding_model = self._build_language_model_config(
            config=embedder_config,
            is_embedding=True,
        )
        models[DEFAULT_EMBEDDING_MODEL_ID] = embedding_model

        return models

    def _build_language_model_config(
        self,
        config: Dict[str, Any],
        is_embedding: bool,
    ) -> LanguageModelConfig:
        """
        Build a LanguageModelConfig from database config dict.

        Args:
            config: Configuration dict from storage
            is_embedding: True for embedding model, False for chat model

        Returns:
            LanguageModelConfig instance
        """
        provider = (config.get("provider") or "").lower()
        model_name = config.get("model_name", "")
        api_key = config.get("api_key")
        base_url = config.get("base_url")
        deployment = config.get("deployment")
        api_version = config.get("api_version")

        # Determine model type based on provider
        model_type = self._get_model_type(provider, is_embedding)

        # Build the config dict
        lm_config_dict = {
            "type": model_type,
            "model": model_name,
            "api_key": api_key,
        }

        if model_type in [ModelType.Chat, ModelType.Embedding]:
            # Map our provider names to LiteLLM provider names
            litellm_provider = self._get_litellm_provider(provider)
            lm_config_dict["model_provider"] = litellm_provider

        # Add optional parameters based on provider
        if provider == "azure" or provider == "azure_openai":
            if base_url:
                lm_config_dict["api_base"] = base_url
            if api_version:
                lm_config_dict["api_version"] = api_version
            if deployment:
                lm_config_dict["deployment_name"] = deployment
        elif base_url:
            lm_config_dict["api_base"] = base_url

        # Add generation parameters for chat models
        if not is_embedding:
            if config.get("temperature") is not None:
                lm_config_dict["temperature"] = config["temperature"]
            if config.get("max_tokens") is not None:
                lm_config_dict["max_tokens"] = config["max_tokens"]
            if config.get("top_p") is not None:
                lm_config_dict["top_p"] = config["top_p"]

        return LanguageModelConfig(**lm_config_dict)

    def _get_model_type(self, provider: str, is_embedding: bool) -> str:
        """
        Determine the model type based on provider.

        Args:
            provider: Provider name (openai, azure, gemini, etc.)
            is_embedding: True for embedding model

        Returns:
            ModelType string value
        """
        provider = provider.lower() if provider else "openai"

        # TODO: use litellm
        if provider in [
            "openai",
            "gemini",
            "anthropic",
            "cohere",
            "mistral",
            "together_ai",
        ]:
            return ModelType.Embedding if is_embedding else ModelType.Chat

        # Azure OpenAI
        if provider in ["azure", "azure_openai"]:
            return (
                ModelType.AzureOpenAIEmbedding
                if is_embedding
                else ModelType.AzureOpenAIChat
            )

        # Default to generic types
        return ModelType.Embedding if is_embedding else ModelType.Chat

    def _get_litellm_provider(self, provider: str) -> str:
        """
        Map our provider names to LiteLLM provider names.

        Args:
            provider: Provider name from database

        Returns:
            LiteLLM-compatible provider name
        """
        provider = provider.lower() if provider else "openai"
        # TODO: use litellm
        # Map provider names to LiteLLM format
        provider_mapping = {
            "openai": "openai",
            "gemini": "gemini",
            "google": "gemini",
            "anthropic": "anthropic",
            "cohere": "cohere",
            "mistral": "mistral",
            "together_ai": "together_ai",
            "together": "together_ai",
            "azure": "azure",
            "azure_openai": "azure",
        }

        return provider_mapping.get(provider, "openai")

    def _build_chunking_config(
        self,
        index_config: Optional[Dict[str, Any]],
    ) -> ChunkingConfig:
        """
        Build ChunkingConfig from database index config.

        Args:
            index_config: Index config dict (optional)

        Returns:
            ChunkingConfig instance
        """
        if index_config:
            strategy = ChunkStrategyType.tokens
            if index_config.get("chunk_strategy") == "sentence":
                strategy = ChunkStrategyType.sentence

            return ChunkingConfig(
                size=index_config.get("chunk_size") or 1200,
                overlap=index_config.get("chunk_overlap") or 100,
                strategy=strategy,
            )
        else:
            # Default config
            return ChunkingConfig()

    def _build_input_config(
        self,
        index_config: Optional[Dict[str, Any]],
    ) -> InputConfig:
        """
        Build InputConfig for reading documents from input folder.

        Args:
            root_folder: Root folder for the GraphRag
            index_config: Index config dict (optional)

        Returns:
            InputConfig instance
        """
        # Determine file type
        file_type = InputFileType.text
        if index_config and index_config.get("file_type"):
            file_type_str = index_config.get("file_type", "").lower()
            if file_type_str == "csv":
                file_type = InputFileType.csv
            elif file_type_str == "json":
                file_type = InputFileType.json

        # Input storage points to input/ subfolder
        input_storage = StorageConfig(
            type=StorageType.file,
            base_dir="input",
        )

        return InputConfig(
            storage=input_storage,
            file_type=file_type,
        )

    def _build_output_config(self, root_folder: Path) -> StorageConfig:
        """
        Build StorageConfig for output (index files).

        Args:
            root_folder: Root folder for the GraphRag

        Returns:
            StorageConfig instance
        """
        return StorageConfig(
            type=StorageType.file,
            base_dir="output",
        )

    def _build_extract_graph_config(
        self,
        index_config: Optional[Dict[str, Any]],
    ) -> ExtractGraphConfig:
        """
        Build ExtractGraphConfig from database index config.

        Args:
            index_config: Index config dict (optional)

        Returns:
            ExtractGraphConfig instance
        """
        if index_config:
            entity_types = index_config.get("entity_types") or [
                "organization",
                "person",
                "geo",
                "event",
            ]
            max_gleanings = index_config.get("max_gleanings") or 1

            return ExtractGraphConfig(
                model_id=DEFAULT_CHAT_MODEL_ID,
                entity_types=entity_types,
                max_gleanings=max_gleanings,
            )
        else:
            return ExtractGraphConfig(
                model_id=DEFAULT_CHAT_MODEL_ID,
            )

    def _build_cluster_graph_config(
        self,
        index_config: Optional[Dict[str, Any]],
    ) -> ClusterGraphConfig:
        """
        Build ClusterGraphConfig from database index config.

        Args:
            index_config: Index config dict (optional)

        Returns:
            ClusterGraphConfig instance
        """
        if index_config and index_config.get("max_cluster_size"):
            return ClusterGraphConfig(
                max_cluster_size=index_config.get("max_cluster_size"),
            )
        else:
            return ClusterGraphConfig()

    def _build_text_embedding_config(self) -> TextEmbeddingConfig:
        """
        Build TextEmbeddingConfig with default embedding model.

        Returns:
            TextEmbeddingConfig instance
        """
        return TextEmbeddingConfig(
            model_id=DEFAULT_EMBEDDING_MODEL_ID,
        )

    # ==================== Search Param Overlay ====================

    def apply_basic_search_params(
        self,
        config: GraphRagConfig,
        params: GraphRagBasicSearchParams,
    ) -> None:
        """
        Overlay Redis-provided basic search params onto GraphRagConfig in-place.

        Args:
            config: Existing GraphRagConfig (loaded from file)
            params: Basic search params from Redis message
        """
        config.basic_search.prompt = build_basic_search_prompt(params.prompt)
        config.basic_search.k = params.k
        config.basic_search.max_context_tokens = params.max_context_tokens

    def apply_local_search_params(
        self,
        config: GraphRagConfig,
        params: GraphRagLocalSearchParams,
    ) -> None:
        """
        Overlay Redis-provided local search params onto GraphRagConfig in-place.

        Args:
            config: Existing GraphRagConfig (loaded from file)
            params: Local search params from Redis message
        """
        config.local_search.prompt = build_local_search_prompt(params.prompt)
        config.local_search.text_unit_prop = params.text_unit_prop
        config.local_search.community_prop = params.community_prop
        config.local_search.conversation_history_max_turns = (
            params.conversation_history_max_turns
        )
        config.local_search.top_k_entities = params.top_k_entities
        config.local_search.top_k_relationships = params.top_k_relationships
        config.local_search.max_context_tokens = params.max_context_tokens
