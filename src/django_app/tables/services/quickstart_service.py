from ai_models.domain.specs import ModelKind
from ai_models.models import (
    DefaultModels,
    EmbeddingConfig,
    EmbeddingConfigTag,
    EmbeddingModel,
    LLMConfig,
    LLMConfigTag,
    LLMModel,
)
from ai_models.services.catalog_model_resolver import CatalogModelResolver
from ai_models.services.config_validation import ConfigValidationService
from django.db import transaction
from django.forms.models import model_to_dict
from loguru import logger
from rbac.authorship import record_last_edits, resolve_author
from src.shared.models import UserAction
from src.shared.system_one.constants import OPENAI_DECISIONS_MODELS, OPENAI_PROVIDER
from tables.models.llm_models import SystemOneConfig
from tables.models.realtime_models import GeminiRealtimeConfig, OpenAIRealtimeConfig
from tables.models.secret_models import Secret
from tables.models.user import User
from tables.services.secrets import secret_service
from user_audit.context import mark_request_handled
from user_audit.recorder import record_user_action
from utils.singleton_meta import SingletonMeta

QUICKSTART_UNEXPECTED_ERROR_MESSAGE = "Quickstart failed. Please try again or contact support."


class QuickstartError(Exception):
    """A quickstart refusal whose message is written for the user and is safe to return."""


class QuickstartUnsupportedProviderError(QuickstartError):
    """Raised when the provider exists but quickstart has no model defaults for it."""


class QuickstartService(metaclass=SingletonMeta):
    QUICKSTART_TAG = "quickstart:latest"

    # `llm_config` and `embedding_config` hold settings that replace the model's catalog
    # defaults in that provider's quickstart config, each only where the catalog allows it
    # for the model. A provider without them keeps the defaults.
    PROVIDER_CONFIGS = {
        "openai": {
            "llm_model": "gpt-6-luna",
            "embedding_model": "text-embedding-3-small",
            # gpt-6-luna is a reasoning model: its reasoning tokens count against
            # max_tokens, so the default 4096 can end a long agent step with
            # finish_reason=length and little visible text. Low effort and a budget
            # below the model's 128000 output limit leave room for the answer.
            "llm_config": {"reasoning_effort": "low", "max_tokens": 100000},
        },
        "gemini": {
            "llm_model": "gemini-3.8-flash",
            "embedding_model": "gemini-embedding-001",
            # The model returns 3072 dimensions by default; the GraphRAG vector store in
            # knowledge_new holds 1536.
            "embedding_config": {"dimensions": 1536},
        },
        "cohere": {
            "llm_model": "command-a-03-2025",
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

        Records a `created` user action for every row the run created, in the request's
        context; a reused Secret is not one of them. Outside a request nothing is recorded.

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

            config_name = self._generate_unique_quickstart_config_name(provider, org_id=org_id)
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
                    provider=provider,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                    author=author,
                )
                embedding_config = self._create_embedder_config(
                    provider=provider,
                    config_name=config_name,
                    org_id=org_id,
                    secret=bundle_secret,
                    author=author,
                )

                realtime_configs = []
                system_one_configs = []
                if provider == "openai":
                    realtime_configs.append(
                        self._create_openai_realtime_config(
                            bundle_secret, config_name, org_id=org_id, author=author
                        )
                    )
                    system_one_configs.append(
                        self._create_openai_system_one_config(
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
                record_last_edits(
                    [llm_config, embedding_config, *realtime_configs, *system_one_configs], user
                )
                created_secrets = [] if secret else [bundle_secret]
                for created in [
                    *created_secrets,
                    llm_config,
                    embedding_config,
                    *realtime_configs,
                    *system_one_configs,
                ]:
                    record_user_action(action=UserAction.CREATED, org_id=org_id, target=created)

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

        Records an `updated` user action on the row when this changed it; an apply that
        changed nothing records nothing, not even the request's fallback record.
        """
        llm = LLMConfig.objects.filter(custom_name=config_name, org_id=org_id).first()
        embedding = EmbeddingConfig.objects.filter(custom_name=config_name, org_id=org_id).first()

        dm = DefaultModels.load_for_org(org_id)
        defaults_before = model_to_dict(dm)
        if llm:
            dm.agent_llm_config = llm
            dm.agent_fcm_llm_config = llm
            dm.project_manager_llm_config = llm
            dm.memory_llm_config = llm
        if embedding:
            dm.memory_embedding_config = embedding
        changed = model_to_dict(dm) != defaults_before
        dm.save()
        if changed:
            record_user_action(action=UserAction.UPDATED, org_id=org_id, target=dm)
        else:
            mark_request_handled()
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
        provider: str,
        config_name: str,
        org_id: int,
        secret: Secret,
        author: User | None,
    ) -> LLMConfig:
        llm_model = self._model(ModelKind.LLM, provider=provider, org_id=org_id, author=author)
        return LLMConfig.objects.create(
            model=llm_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
            created_by=author,
            parameters=self._parameters(
                ModelKind.LLM,
                provider=provider,
                model_name=llm_model.name,
                org_id=org_id,
                overrides=self.PROVIDER_CONFIGS[provider].get("llm_config", {}),
            ),
        )

    def _create_embedder_config(
        self,
        *,
        provider: str,
        config_name: str,
        org_id: int,
        secret: Secret,
        author: User | None,
    ) -> EmbeddingConfig:
        embedder_model = self._model(
            ModelKind.EMBEDDING, provider=provider, org_id=org_id, author=author
        )
        return EmbeddingConfig.objects.create(
            model=embedder_model,
            custom_name=config_name,
            org_id=org_id,
            api_key_secret=secret,
            created_by=author,
            parameters=self._parameters(
                ModelKind.EMBEDDING,
                provider=provider,
                model_name=embedder_model.name,
                org_id=org_id,
                overrides=self.PROVIDER_CONFIGS[provider].get("embedding_config", {}),
            ),
        )

    def _model(
        self, kind: ModelKind, *, provider: str, org_id: int, author: User | None
    ) -> LLMModel | EmbeddingModel:
        """Return the model row of the provider's quickstart model, resolved like the API does.

        Quickstart's configs have an empty `connection`, so the bundle secret goes to
        wherever the model's name routes, which for the fixed name is the provider's own
        endpoint. An organization's own row is locked until the quickstart commits: a
        concurrent rename locks it too (`check_llm_model_write`), so it either waits and
        then counts the configs made here, or lands first, and the renamed row no longer
        matches and is resolved again. Must run inside the quickstart's transaction.

        Raises:
            UnknownCatalogModelError: The provider or model has no row and takes no custom models.
        """
        model_key = "llm_model" if kind == ModelKind.LLM else "embedding_model"
        provider_field = "llm_provider" if kind == ModelKind.LLM else "embedding_provider"
        resolver = CatalogModelResolver()
        model = resolver.resolve(
            kind, provider, self.PROVIDER_CONFIGS[provider][model_key], org_id=org_id, author=author
        )
        # A built-in row is immutable, so it stays unlocked. An unsaved row comes back
        # from `save_if_new` either created by this transaction or locked and still matching.
        if model.pk is None or model.org_id is None:
            return resolver.save_if_new(model)
        locked = (
            type(model)
            .objects.select_for_update(no_key=True, of=("self",))
            .filter(pk=model.pk)
            .first()
        )
        resolved_key = (model.name, getattr(model, f"{provider_field}_id"))
        if locked is None or (locked.name, getattr(locked, f"{provider_field}_id")) != resolved_key:
            return self._model(kind, provider=provider, org_id=org_id, author=author)
        return locked

    def _parameters(
        self, kind: ModelKind, *, provider: str, model_name: str, org_id: int, overrides: dict
    ) -> dict:
        """Return the model's catalog defaults with the overrides the catalog allows for it.

        Raises:
            ConfigValidationError: The result does not pass the catalog's write rules.
        """
        service = ConfigValidationService()
        parameters = {
            **service.defaults(kind, provider, model_name),
            **service.allowed_parameters(kind, provider, model_name, overrides),
        }
        service.validate(kind, provider, model_name, parameters, {}, org_id)
        return parameters

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

    def _create_openai_system_one_config(
        self, secret: Secret, config_name: str, org_id: int, author: User | None
    ) -> SystemOneConfig:
        return SystemOneConfig.objects.create(
            custom_name=config_name,
            provider=OPENAI_PROVIDER,
            model_name=OPENAI_DECISIONS_MODELS[0],
            api_key_secret=secret,
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

    def _generate_unique_quickstart_config_name(self, provider: str, *, org_id: int) -> str:
        """
        Generate unique quickstart configuration name

        Logic:
        - Base name: quickstart_{provider}
        - If no configs exist: return quickstart_{provider}
        - If configs exist: return quickstart_{provider}_{next_number}

        Numbering is per org, like the configs' unique-name constraints, so another
        org's configs never shift this org's numbers.
        """
        base_name = f"quickstart_{provider}"

        existing_names = self._get_taken_config_names(base_name, org_id=org_id)

        if not existing_names:
            return base_name

        max_number = 0
        for name in existing_names:
            if name == base_name:
                max_number = max(max_number, 0)
            elif name.startswith(f"{base_name}_"):
                suffix = name[len(f"{base_name}_") :]
                # A huge number would push the bundle Secret name past its max_length.
                if len(suffix) > 9:
                    continue
                try:
                    number = int(suffix)
                    max_number = max(max_number, number)
                except ValueError:
                    # Skip non-numeric suffixes
                    continue

        # The max skips long suffixes, so max + 1 can be one of those names.
        number = max_number + 1
        while f"{base_name}_{number}" in existing_names:
            number += 1
        return f"{base_name}_{number}"

    def _get_taken_config_names(self, base_name: str, *, org_id: int) -> set[str]:
        """Return the org's names starting with base_name that a new bundle can't reuse.

        Besides config names, this includes the bundle names of the org's active
        quickstart Secrets: deleting a bundle's configs keeps its Secret, and
        creating a Secret with the same name again would break its unique constraint.
        """
        existing_names = set()

        config_models = [
            LLMConfig,
            EmbeddingConfig,
            SystemOneConfig,
            OpenAIRealtimeConfig,
            GeminiRealtimeConfig,
        ]

        for model in config_models:
            names = model.objects.filter(
                org_id=org_id, custom_name__startswith=base_name
            ).values_list("custom_name", flat=True)
            existing_names.update(names)

        secret_suffix = self._bundle_secret_name(bundle_name="")
        secret_names = Secret.objects.filter(
            org_id=org_id,
            name__startswith=base_name.replace("_", "-"),
            name__endswith=secret_suffix,
        ).values_list("name", flat=True)
        existing_names.update(
            name.removesuffix(secret_suffix).replace("-", "_") for name in secret_names
        )

        return existing_names
