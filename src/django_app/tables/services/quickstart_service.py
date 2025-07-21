from typing import Set
from loguru import logger
from django.db import transaction

from utils.singleton_meta import SingletonMeta
from tables.models.llm_models import (
    LLMModel,
    LLMConfig,
    RealtimeModel,
    RealtimeConfig,
    RealtimeTranscriptionModel,
    RealtimeTranscriptionConfig,
)
from tables.models.embedding_models import EmbeddingModel, EmbeddingConfig
from tables.models.provider import Provider


class QuickstartService(metaclass=SingletonMeta):

    PROVIDER_CONFIGS = {
        "openai": {
            "llm_model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small",
            "realtime_model": "gpt-4o-mini-realtime-preview-2024-12-17",
            "realtime_transcription_model": "whisper-1",
        },
        # TODO: need to test models
        "gemini": {
            "llm_model": "gemini-1.5-pro",
            "embedding_model": "text-embedding-004",
        },
        "cohere": {
            "llm_model": "command-r-plus",
            "embedding_model": "embed-english-v3.0",
        },
        "mistral": {
            "llm_model": "mistral-large-latest",
            "embedding_model": "mistral-embed",
        },
    }

    def __init__(self): ...

    def quickstart(self, provider: str, api_key: str) -> dict:
        try:
            if provider not in self.PROVIDER_CONFIGS:
                supported = ", ".join(self.PROVIDER_CONFIGS.keys())
                raise KeyError(
                    f"Unsupported provider: {provider}. Supported providers: {supported}"
                )

            config_name = self._generate_unique_quickstart_config_name(provider)
            provider_obj = Provider.objects.get(name=provider)
            with transaction.atomic():
                self._create_llm_model_config(provider_obj, api_key, config_name)
                self._create_embedder_config(provider_obj, api_key, config_name)
                if provider == "openai":
                    self._create_realtime_config(provider_obj, api_key, config_name)
                    self._create_realtime_transcription_config(
                        provider_obj, api_key, config_name
                    )
            logger.success(
                f"Quickstart configuration: {config_name} created successfully!"
            )
            return {
                "success": True,
                "config_name": config_name,
            }
        except Exception as e:
            logger.error(f"Quickstart error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_supported_providers(self):
        return self.PROVIDER_CONFIGS.keys()

    def _create_llm_model_config(
        self, provider: Provider, api_key: str, config_name: str
    ) -> None:
        llm_model = self._get_or_create_llm_model(provider)
        LLMConfig.objects.create(
            model=llm_model, custom_name=config_name, api_key=api_key
        )

    def _create_embedder_config(
        self, provider: Provider, api_key: str, config_name: str
    ) -> None:
        embedder_model = self._get_or_create_embedder_model(provider)
        EmbeddingConfig.objects.create(
            model=embedder_model, custom_name=config_name, api_key=api_key
        )

    def _create_realtime_config(
        self, provider: Provider, api_key: str, config_name: str
    ) -> None:
        realtime_model = self._get_or_create_realtime_model(provider)
        RealtimeConfig.objects.create(
            realtime_model=realtime_model, custom_name=config_name, api_key=api_key
        )

    def _create_realtime_transcription_config(
        self, provider: Provider, api_key: str, config_name: str
    ) -> None:
        realtime_transcription_model = self._get_or_create_realtime_transcription_model(
            provider
        )
        RealtimeTranscriptionConfig.objects.create(
            realtime_transcription_model=realtime_transcription_model,
            custom_name=config_name,
            api_key=api_key,
        )

    def _get_or_create_llm_model(self, provider: Provider):
        llm_model_name = self.PROVIDER_CONFIGS.get(provider.name, {}).get("llm_model")
        if llm_model_name is None:
            raise KeyError(
                f"Can not get 'llm_model' from PROVIDER_CONFIGS for {provider.name}"
            )
        llm_model, created = LLMModel.objects.get_or_create(
            llm_provider=provider, name=llm_model_name
        )
        if created:
            logger.info(
                f"Created LLM model: {llm_model.name}, provider: {provider.name}"
            )
        return llm_model

    def _get_or_create_embedder_model(self, provider: Provider):

        embedder_model_name = self.PROVIDER_CONFIGS.get(provider.name, {}).get(
            "embedding_model"
        )
        if embedder_model_name is None:
            raise KeyError(
                f"Can not get 'embedding_model' from PROVIDER_CONFIGS for {provider.name}"
            )

        embedder_model, created = EmbeddingModel.objects.get_or_create(
            embedding_provider=provider, name=embedder_model_name
        )
        if created:
            logger.info(
                f"Created embedding model: {embedder_model.name}, provider: {provider.name}"
            )
        return embedder_model

    def _get_or_create_realtime_model(self, provider: Provider):

        realtime_model_name = self.PROVIDER_CONFIGS.get(provider.name, {}).get(
            "realtime_model"
        )
        if realtime_model_name is None:
            raise KeyError(
                f"Can not get 'realtime_model_name' from PROVIDER_CONFIGS for {provider.name}"
            )

        realtime_model, created = RealtimeModel.objects.get_or_create(
            provider=provider, name=realtime_model_name
        )
        if created:
            logger.info(
                f"Created realtime model: {realtime_model.name}, provider: {provider.name}"
            )
        return realtime_model

    def _get_or_create_realtime_transcription_model(self, provider: Provider):
        realtime_transcription_model_name = self.PROVIDER_CONFIGS.get(
            provider.name, {}
        ).get("realtime_transcription_model")
        if realtime_transcription_model_name is None:
            raise KeyError(
                f"Can not get 'realtime_transcription_model_name' from PROVIDER_CONFIGS for {provider.name}"
            )

        realtime_transcription_model, created = (
            RealtimeTranscriptionModel.objects.get_or_create(
                provider=provider, name=realtime_transcription_model_name
            )
        )
        if created:
            logger.info(
                f"Created realtime transcription model: {realtime_transcription_model.name}, provider: {provider.name}"
            )
        return realtime_transcription_model

    def _generate_unique_quickstart_config_name(self, provider: str) -> str:
        """
        Generate unique quickstart configuration name

        Logic:
        - Base name: quickstart_{provider}
        - If no configs exist: return quickstart_{provider}
        - If configs exist: return quickstart_{provider}_{next_number}

        Args:
            provider: Provider name

        Returns:
            str: Unique configuration name
        """
        base_name = f"quickstart_{provider}"

        existing_names = self._get_existing_config_names(base_name)

        if not existing_names:
            return base_name

        max_number = 0
        for name in existing_names:
            if name == base_name:
                max_number = max(max_number, 0)
            elif name.startswith(f"{base_name}_"):
                suffix = name[len(f"{base_name}_") :]
                try:
                    number = int(suffix)
                    max_number = max(max_number, number)
                except ValueError:
                    # Skip non-numeric suffixes
                    continue

        if max_number == 0 and base_name in existing_names:
            return f"{base_name}_1"
        else:
            return f"{base_name}_{max_number + 1}"

    def _get_existing_config_names(self, base_name: str) -> Set[str]:
        """Get all existing configuration names that start with base_name"""
        existing_names = set()

        config_models = [
            LLMConfig,
            EmbeddingConfig,
            RealtimeConfig,
            RealtimeTranscriptionConfig,
        ]

        for model in config_models:
            names = model.objects.filter(custom_name__startswith=base_name).values_list(
                "custom_name", flat=True
            )
            existing_names.update(names)

        return existing_names
