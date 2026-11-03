from django.db import transaction
from loguru import logger
from rbac.authorship import record_last_edits, resolve_author
from tables.models.default_models import DefaultModels
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
)
from tables.models.provider import Provider
from tables.models.realtime_models import GeminiRealtimeConfig, OpenAIRealtimeConfig
from tables.models.secret_models import Secret
from tables.models.tag_models import (
    EmbeddingConfigTag,
    LLMConfigTag,
)
from tables.models.user import User
from tables.services.secrets import secret_service
from utils.singleton_meta import SingletonMeta

QUICKSTART_UNEXPECTED_ERROR_MESSAGE = "Quickstart failed. Please try again or contact support."


class QuickstartError(Exception):
    """A quickstart refusal whose message is written for the user and is safe to return."""


class QuickstartUnsupportedProviderError(QuickstartError):
    """Raised when the provider exists but quickstart has no model defaults for it."""


class QuickstartCustomModelError(QuickstartError):
    """Raised when quickstart would attach its secret to an org model with a custom `base_url`."""


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

    def quickstart(
        self,
        *,
        provider: str,
        org_id: int,
        user: object,
        api_key: str | None = None,
        secret: Secret | None = None,
    ) -> dict:
        """Create matched provider configs sharing one Secret, authored and last edited by `user`.

        Exactly one of `api_key` (cold start — a Secret is created and named after
        the bundle) or `secret` (reuse — nothing is created) is expected; the
        serializer enforces that. A `user` that is not a real user leaves the rows unauthored.

        A failure returns `{"success": False, "error": <message>, "unexpected": <bool>}`.
        A `QuickstartError` carries its own user-facing message (`unexpected` is False);
        any other exception is logged with its traceback and reported only as
        `QUICKSTART_UNEXPECTED_ERROR_MESSAGE`, so internal details never reach the client.
        """
        try:
            if provider not in self.PROVIDER_CONFIGS:
                supported = ", ".join(self.PROVIDER_CONFIGS.keys())
                raise QuickstartUnsupportedProviderError(
                    f"Unsupported provider: {provider}. Supported providers: {supported}"
                )

            config_name = self._generate_unique_quickstart_config_name(provider)
            provider_obj = Provider.objects.get(name=provider)
            author = resolve_author(user)
            with transaction.atomic():
                # One Secret backs the whole bundle. Resolved before any config
                # exists, so every config can set the FK on its INSERT.
                bundle_secret = secret or secret_service.create(
                    text=api_key,
                    org_id=org_id,
                    name=self._bundle_secret_name(bundle_name=config_name),
                    created_by=author,
                )
                llm_config = self._create_llm_model_config(
                    provider=provider_obj,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                    author=author,
                )
                embedding_config = self._create_embedder_config(
                    provider=provider_obj,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                    author=author,
                )

                realtime_configs = []
                if provider == "openai":
                    realtime_configs.append(
                        self._create_openai_realtime_config(
                            bundle_secret, config_name, org_id=org_id, author=author
                        )
                    )
                elif provider == "gemini":
                    realtime_configs.append(
                        self._create_gemini_realtime_config(
                            bundle_secret, config_name, org_id=org_id, author=author
                        )
                    )

                self._apply_quickstart_tag(
                    llm_config=llm_config,
                    embedding_config=embedding_config,
                    org_id=org_id,
                )
                record_last_edits([llm_config, embedding_config, *realtime_configs], user)

            logger.success(f"Quickstart configuration: {config_name} created successfully!")
            return {
                "success": True,
                "config_name": config_name,
                "llm_config": llm_config,
                "embedding_config": embedding_config,
            }
        except QuickstartError as error:
            logger.warning("Quickstart refused for provider {}: {}", provider, error)
            return {
                "success": False,
                "error": str(error),
                "unexpected": False,
            }
        except Exception:
            logger.exception("Quickstart failed for provider {} in org {}", provider, org_id)
            return {
                "success": False,
                "error": QUICKSTART_UNEXPECTED_ERROR_MESSAGE,
                "unexpected": True,
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
        *,
        org_id: int,
    ) -> None:
        """Moves the predefined 'quickstart' tag to the newly created configs within one org."""
        tag_map = [
            (LLMConfigTag, LLMConfig, llm_config),
            (EmbeddingConfigTag, EmbeddingConfig, embedding_config),
        ]

        for tag_model, config_model, new_config in tag_map:
            tag, _ = tag_model.objects.update_or_create(
                name=self.QUICKSTART_TAG, defaults={"predefined": True}
            )
            previous = config_model.objects.filter(tags=tag, org_id=org_id).exclude(
                pk=new_config.pk if new_config else None
            )
            for old in previous:
                old.tags.remove(tag)
            if new_config:
                new_config.tags.add(tag)

    def apply_to_default_models(self, config_name: str, *, org_id: int) -> DefaultModels:
        """
        Applies the given quickstart config to the organization's DefaultModels row.
        Sets all relevant FKs based on what configs exist for that config_name.
        """
        llm = LLMConfig.objects.filter(custom_name=config_name, org_id=org_id).first()
        embedding = EmbeddingConfig.objects.filter(custom_name=config_name, org_id=org_id).first()

        dm = DefaultModels.load_for_org(org_id)
        if llm:
            dm.agent_llm_config = llm
            dm.agent_fcm_llm_config = llm
            dm.project_manager_llm_config = llm
            dm.memory_llm_config = llm
        if embedding:
            dm.memory_embedding_config = embedding
        dm.save()
        return dm

    def is_synced(self, last_config: dict, *, org_id: int) -> bool:
        """
        Returns True if the organization's DefaultModels FKs all point to the configs
        from the given last_config dict.
        """
        dm = DefaultModels.load_for_org(org_id)
        checks = []
        if last_config.get("llm_config"):
            checks.append(dm.agent_llm_config_id == last_config["llm_config"].id)
        if last_config.get("embedding_config"):
            checks.append(dm.memory_embedding_config_id == last_config["embedding_config"].id)
        return bool(checks) and all(checks)

    def _bundle_secret_name(self, *, bundle_name: str) -> str:
        """Name the bundle's Secret after the bundle it backs, not after one of the
        config types that reference it — a single Secret serves them all."""
        return f"{bundle_name.replace('_', '-')}-api-key"

    def _create_llm_model_config(
        self,
        *,
        provider: Provider,
        config_name: str,
        org_id: int,
        secret: Secret,
        author: User | None,
    ) -> LLMConfig:
        llm_model = self._get_or_create_llm_model(provider=provider, org_id=org_id, author=author)
        return LLMConfig.objects.create(
            model=llm_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
            created_by=author,
        )

    def _create_embedder_config(
        self,
        *,
        provider: Provider,
        config_name: str,
        org_id: int,
        secret: Secret,
        author: User | None,
    ) -> EmbeddingConfig:
        embedder_model = self._get_or_create_embedder_model(
            provider=provider, org_id=org_id, author=author
        )
        return EmbeddingConfig.objects.create(
            model=embedder_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
            created_by=author,
        )

    def _create_openai_realtime_config(
        self, secret: Secret, config_name: str, org_id: int, author: User | None
    ) -> OpenAIRealtimeConfig:
        return OpenAIRealtimeConfig.objects.create(
            custom_name=config_name,
            api_key_secret=secret,
            transcription_api_key_secret=secret,
            org_id=org_id,
            created_by=author,
        )

    def _create_gemini_realtime_config(
        self, secret: Secret, config_name: str, org_id: int, author: User | None
    ) -> GeminiRealtimeConfig:
        return GeminiRealtimeConfig.objects.create(
            custom_name=config_name,
            api_key_secret=secret,
            org_id=org_id,
            created_by=author,
        )

    def _get_or_create_llm_model(self, *, provider: Provider, org_id: int, author: User | None):
        llm_model_name = self.PROVIDER_CONFIGS.get(provider.name, {}).get("llm_model")
        if llm_model_name is None:
            raise KeyError(f"Can not get 'llm_model' from PROVIDER_CONFIGS for {provider.name}")
        return self._get_or_create_model(
            model_class=LLMModel,
            provider_field="llm_provider",
            provider=provider,
            name=llm_model_name,
            org_id=org_id,
            author=author,
        )

    def _get_or_create_embedder_model(
        self, *, provider: Provider, org_id: int, author: User | None
    ):
        embedder_model_name = self.PROVIDER_CONFIGS.get(provider.name, {}).get("embedding_model")
        if embedder_model_name is None:
            raise KeyError(
                f"Can not get 'embedding_model' from PROVIDER_CONFIGS for {provider.name}"
            )
        return self._get_or_create_model(
            model_class=EmbeddingModel,
            provider_field="embedding_provider",
            provider=provider,
            name=embedder_model_name,
            org_id=org_id,
            author=author,
        )

    def _get_or_create_model(
        self,
        *,
        model_class: type[LLMModel] | type[EmbeddingModel],
        provider_field: str,
        provider: Provider,
        name: str,
        org_id: int,
        author: User | None,
    ) -> LLMModel | EmbeddingModel:
        """Return the model quickstart attaches the bundle secret to, creating it if missing.

        The built-in catalog model wins over the org's own model of the same name. A
        custom model can point at any `base_url`, and anyone who may create models in
        the org could make one under the catalog name ahead of a quickstart, which
        would then send the bundle secret to that URL. So the org's model is only used
        when there is no built-in and it has no `base_url` of its own; with one,
        quickstart refuses rather than attach the key.

        Raises:
            QuickstartCustomModelError: No built-in exists and the org's model of
                this name has a custom `base_url`.
        """
        candidates = model_class.objects.filter(**{provider_field: provider, "name": name})
        built_in_model = candidates.filter(org_id__isnull=True).first()
        if built_in_model is not None:
            return built_in_model
        # Locked until the quickstart's transaction commits, and `base_url` read from
        # the locked row: a concurrent edit of this model's `base_url` locks it too
        # (check_llm_model_write / check_embedding_model_write), so it either lands
        # first and is refused below, or waits and then counts the config attached here.
        # Built-in models are immutable and need no lock.
        own_model = candidates.filter(org_id=org_id).select_for_update().first()
        if own_model is not None:
            if own_model.base_url:
                raise QuickstartCustomModelError(
                    f'The organization\'s custom model "{own_model.name}" sends requests '
                    "to a custom URL, so quickstart will not attach a key to it."
                )
            return own_model
        model = model_class.objects.create(
            **{provider_field: provider},
            name=name,
            org_id=org_id,
            is_custom=True,
            created_by=author,
        )
        logger.info(
            "Created custom {} {} for provider {} in org {}",
            model_class.__name__,
            model.name,
            provider.name,
            org_id,
        )
        return model

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

    def _get_existing_config_names(self, base_name: str) -> set[str]:
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
