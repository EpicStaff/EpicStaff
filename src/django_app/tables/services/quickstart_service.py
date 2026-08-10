from typing import Set
from loguru import logger
from django.db import transaction

from utils.singleton_meta import SingletonMeta
from tables.models.llm_models import (
    LLMModel,
    LLMConfig,
)
from tables.models.embedding_models import EmbeddingModel, EmbeddingConfig
from tables.models.provider import Provider
from tables.models.default_models import DefaultModels
from tables.models.realtime_models import OpenAIRealtimeConfig, GeminiRealtimeConfig
from tables.models.tag_models import (
    LLMConfigTag,
    EmbeddingConfigTag,
)


class QuickstartService(metaclass=SingletonMeta):
    QUICKSTART_TAG = "quickstart:latest"

    PROVIDER_CONFIGS = {
        "openai": {
            "llm_model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small",
        },
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

    def quickstart(self, provider: str, api_key: str, org_id: int) -> dict:
        try:
            if provider not in self.PROVIDER_CONFIGS:
                supported = ", ".join(self.PROVIDER_CONFIGS.keys())
                raise KeyError(
                    f"Unsupported provider: {provider}. Supported providers: {supported}"
                )

            config_name = self._generate_unique_quickstart_config_name(provider)
            provider_obj = Provider.objects.get(name=provider)
            with transaction.atomic():
                llm_config = self._create_llm_model_config(
                    provider_obj, api_key, config_name, org_id=org_id
                )
                embedding_config = self._create_embedder_config(
                    provider_obj, api_key, config_name, org_id=org_id
                )

                if provider == "openai":
                    self._create_openai_realtime_config(
                        api_key, config_name, org_id=org_id
                    )
                elif provider == "gemini":
                    self._create_gemini_realtime_config(
                        api_key, config_name, org_id=org_id
                    )

                self._apply_quickstart_tag(llm_config, embedding_config)

            logger.success(
                f"Quickstart configuration: {config_name} created successfully!"
            )
            return {
                "success": True,
                "config_name": config_name,
                "llm_config": llm_config,
                "embedding_config": embedding_config,
            }
        except Exception as e:
            logger.error(f"Quickstart error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_supported_providers(self):
        return self.PROVIDER_CONFIGS.keys()

    def get_last_quickstart(self, org_id: int) -> dict | None:
        """
        Returns the active quickstart config for the given organization —
        identified by the predefined 'quickstart' tag on LLMConfig. The tag is
        moved to the newest config on every quickstart run. Scoped to org_id so
        one org never sees another org's quickstart config (or its api key).
        Returns None if no quickstart has been run in this org.
        """
        llm = LLMConfig.objects.filter(
            tags__name=self.QUICKSTART_TAG, tags__predefined=True, org_id=org_id
        ).first()
        if not llm:
            return None
        return {
            "config_name": llm.custom_name,
            "llm_config": llm,
            "embedding_config": EmbeddingConfig.objects.filter(
                tags__name=self.QUICKSTART_TAG, tags__predefined=True, org_id=org_id
            ).first(),
        }

    def _apply_quickstart_tag(
        self,
        llm_config: LLMConfig,
        embedding_config: EmbeddingConfig,
    ) -> None:
        """
        Moves the predefined 'quickstart' tag to the newly created configs.
        Removes it from any previous quickstart configs first.
        """
        tag_map = [
            (LLMConfigTag, LLMConfig, llm_config),
            (EmbeddingConfigTag, EmbeddingConfig, embedding_config),
        ]

        for tag_model, config_model, new_config in tag_map:
            tag, _ = tag_model.objects.update_or_create(
                name=self.QUICKSTART_TAG, defaults={"predefined": True}
            )
            # Remove from previous holders
            for old in config_model.objects.filter(tags=tag).exclude(
                pk=new_config.pk if new_config else None
            ):
                old.tags.remove(tag)
            if new_config:
                new_config.tags.add(tag)

    def apply_to_default_models(self, config_name: str) -> DefaultModels:
        """
        Applies the given quickstart config to DefaultModels singleton.
        Sets all relevant FKs based on what configs exist for that config_name.
        """
        llm = LLMConfig.objects.filter(custom_name=config_name).first()
        embedding = EmbeddingConfig.objects.filter(custom_name=config_name).first()

        dm = DefaultModels.load()
        if llm:
            dm.agent_llm_config = llm
            dm.agent_fcm_llm_config = llm
            dm.project_manager_llm_config = llm
            dm.memory_llm_config = llm
        if embedding:
            dm.memory_embedding_config = embedding
        dm.save()
        return dm

    def is_synced(self, last_config: dict) -> bool:
        """
        Returns True if DefaultModels FKs all point to the configs
        from the given last_config dict.
        """
        dm = DefaultModels.load()
        checks = []
        if last_config.get("llm_config"):
            checks.append(dm.agent_llm_config_id == last_config["llm_config"].id)
        if last_config.get("embedding_config"):
            checks.append(
                dm.memory_embedding_config_id == last_config["embedding_config"].id
            )
        return bool(checks) and all(checks)

    def _create_llm_model_config(
        self, provider: Provider, api_key: str, config_name: str, org_id: int
    ) -> LLMConfig:
        llm_model = self._get_or_create_llm_model(provider)
        return LLMConfig.objects.create(
            model=llm_model, custom_name=config_name, api_key=api_key, org_id=org_id
        )

    def _create_embedder_config(
        self, provider: Provider, api_key: str, config_name: str, org_id: int
    ) -> EmbeddingConfig:
        embedder_model = self._get_or_create_embedder_model(provider)
        return EmbeddingConfig.objects.create(
            model=embedder_model,
            custom_name=config_name,
            api_key=api_key,
            org_id=org_id,
        )

    def _create_openai_realtime_config(
        self, api_key: str, config_name: str, org_id: int
    ) -> OpenAIRealtimeConfig:
        return OpenAIRealtimeConfig.objects.create(
            custom_name=config_name,
            api_key=api_key,
            transcription_api_key=api_key,
            org_id=org_id,
        )

    def _create_gemini_realtime_config(
        self, api_key: str, config_name: str, org_id: int
    ) -> GeminiRealtimeConfig:
        return GeminiRealtimeConfig.objects.create(
            custom_name=config_name,
            api_key=api_key,
            org_id=org_id,
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
        ]

        for model in config_models:
            names = model.objects.filter(custom_name__startswith=base_name).values_list(
                "custom_name", flat=True
            )
            existing_names.update(names)

        return existing_names
