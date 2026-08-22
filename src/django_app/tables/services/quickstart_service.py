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
from tables.models.default_models import DefaultModels
from tables.models.secret_models import Secret
from tables.models.tag_models import (
    LLMConfigTag,
    EmbeddingConfigTag,
    RealtimeConfigTag,
    RealtimeTranscriptionConfigTag,
)
from tables.services.secrets import secret_service


class QuickstartService(metaclass=SingletonMeta):
    QUICKSTART_TAG = "quickstart:latest"

    PROVIDER_CONFIGS = {
        "openai": {
            "llm_model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small",
            "realtime_model": "gpt-4o-mini-realtime-preview-2024-12-17",
            "realtime_transcription_model": "whisper-1",
        },
        "gemini": {
            "llm_model": "gemini-1.5-pro",
            "embedding_model": "text-embedding-004",
            "realtime_model": "gemini-2.0-flash-live-001",
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

    def quickstart(
        self,
        *,
        provider: str,
        org_id: int,
        api_key: str | None = None,
        secret: Secret | None = None,
    ) -> dict:
        """Create a matched set of provider configs backed by a single Secret.

        Exactly one of `api_key` (cold start — a Secret is created and named after
        the bundle) or `secret` (reuse — nothing is created) is expected; the
        serializer enforces that.
        """
        try:
            if provider not in self.PROVIDER_CONFIGS:
                supported = ", ".join(self.PROVIDER_CONFIGS.keys())
                raise KeyError(
                    f"Unsupported provider: {provider}. Supported providers: {supported}"
                )

            config_name = self._generate_unique_quickstart_config_name(provider)
            provider_obj = Provider.objects.get(name=provider)
            with transaction.atomic():
                # One Secret backs the whole bundle. Resolved before any config
                # exists, so every config can set the FK on its INSERT.
                bundle_secret = secret or secret_service.create(
                    text=api_key,
                    org_id=org_id,
                    name=self._bundle_secret_name(bundle_name=config_name),
                )
                llm_config = self._create_llm_model_config(
                    provider=provider_obj,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                )
                embedding_config = self._create_embedder_config(
                    provider=provider_obj,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                )
                realtime_config = None
                realtime_transcription_config = None
                if provider == "openai":
                    realtime_config = self._create_realtime_config(
                        provider=provider_obj,
                        config_name=config_name,
                        org_id=org_id,
                        secret=bundle_secret,
                    )
                    realtime_transcription_config = (
                        self._create_realtime_transcription_config(
                            provider=provider_obj,
                            config_name=config_name,
                            org_id=org_id,
                            secret=bundle_secret,
                        )
                    )

                elif provider == "gemini":
                    self._create_realtime_config(
                        provider=provider_obj,
                        config_name=config_name,
                        org_id=org_id,
                        secret=bundle_secret,
                    )

                self._apply_quickstart_tag(
                    llm_config=llm_config,
                    embedding_config=embedding_config,
                    realtime_config=realtime_config,
                    realtime_transcription_config=realtime_transcription_config,
                )
            logger.success(
                f"Quickstart configuration: {config_name} created successfully!"
            )
            return {
                "success": True,
                "config_name": config_name,
                "llm_config": llm_config,
                "embedding_config": embedding_config,
                "realtime_config": realtime_config,
                "realtime_transcription_config": realtime_transcription_config,
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
            "realtime_config": RealtimeConfig.objects.filter(
                tags__name=self.QUICKSTART_TAG, tags__predefined=True, org_id=org_id
            ).first(),
            "realtime_transcription_config": RealtimeTranscriptionConfig.objects.filter(
                tags__name=self.QUICKSTART_TAG, tags__predefined=True, org_id=org_id
            ).first(),
        }

    def _apply_quickstart_tag(
        self,
        llm_config: LLMConfig,
        embedding_config: EmbeddingConfig,
        realtime_config: RealtimeConfig | None,
        realtime_transcription_config: RealtimeTranscriptionConfig | None,
    ) -> None:
        """
        Moves the predefined 'quickstart' tag to the newly created configs.
        Removes it from any previous quickstart configs first.
        """
        tag_map = [
            (LLMConfigTag, LLMConfig, llm_config),
            (EmbeddingConfigTag, EmbeddingConfig, embedding_config),
            (RealtimeConfigTag, RealtimeConfig, realtime_config),
            (
                RealtimeTranscriptionConfigTag,
                RealtimeTranscriptionConfig,
                realtime_transcription_config,
            ),
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
            # Apply to new config (skip if not created for this provider, e.g. realtime for non-openai)
            if new_config:
                new_config.tags.add(tag)

    def apply_to_default_models(self, config_name: str) -> DefaultModels:
        """
        Applies the given quickstart config to DefaultModels singleton.
        Sets all relevant FKs based on what configs exist for that config_name.
        """
        llm = LLMConfig.objects.filter(custom_name=config_name).first()
        embedding = EmbeddingConfig.objects.filter(custom_name=config_name).first()
        realtime = RealtimeConfig.objects.filter(custom_name=config_name).first()
        transcription = RealtimeTranscriptionConfig.objects.filter(
            custom_name=config_name
        ).first()

        dm = DefaultModels.load()
        if llm:
            dm.agent_llm_config = llm
            dm.agent_fcm_llm_config = llm
            dm.project_manager_llm_config = llm
            dm.memory_llm_config = llm
        if embedding:
            dm.memory_embedding_config = embedding
        if realtime:
            dm.voice_llm_config = realtime
        if transcription:
            dm.transcription_llm_config = transcription
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
        if last_config.get("realtime_config"):
            checks.append(dm.voice_llm_config_id == last_config["realtime_config"].id)
        if last_config.get("realtime_transcription_config"):
            checks.append(
                dm.transcription_llm_config_id
                == last_config["realtime_transcription_config"].id
            )
        return bool(checks) and all(checks)

    def _bundle_secret_name(self, *, bundle_name: str) -> str:
        """Name the bundle's Secret after the bundle it backs, not after one of the
        config types that reference it — a single Secret serves them all."""
        return f"{bundle_name.replace('_', '-')}-api-key"

    def _create_llm_model_config(
        self, *, provider: Provider, config_name: str, org_id: int, secret: Secret
    ) -> LLMConfig:
        llm_model = self._get_or_create_llm_model(provider=provider)
        return LLMConfig.objects.create(
            model=llm_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
        )

    def _create_embedder_config(
        self, *, provider: Provider, config_name: str, org_id: int, secret: Secret
    ) -> EmbeddingConfig:
        embedder_model = self._get_or_create_embedder_model(provider=provider)
        return EmbeddingConfig.objects.create(
            model=embedder_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
        )

    def _create_realtime_config(
        self, *, provider: Provider, config_name: str, org_id: int, secret: Secret
    ) -> RealtimeConfig:
        realtime_model = self._get_or_create_realtime_model(provider=provider)
        return RealtimeConfig.objects.create(
            realtime_model=realtime_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
        )

    def _create_realtime_transcription_config(
        self, *, provider: Provider, config_name: str, org_id: int, secret: Secret
    ) -> RealtimeTranscriptionConfig:
        realtime_transcription_model = self._get_or_create_realtime_transcription_model(
            provider=provider
        )
        return RealtimeTranscriptionConfig.objects.create(
            realtime_transcription_model=realtime_transcription_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
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

        (
            realtime_transcription_model,
            created,
        ) = RealtimeTranscriptionModel.objects.get_or_create(
            provider=provider, name=realtime_transcription_model_name
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
