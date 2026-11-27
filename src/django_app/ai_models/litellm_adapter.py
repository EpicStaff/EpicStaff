"""The only code that reads LiteLLM's model data.

LiteLLM's internal APIs move between releases; when a bump breaks one, this module is
the one place to fix, and every failure surfaces as `CatalogSourceError` instead of a
partial catalog.
"""

import inspect
import os
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from importlib.metadata import version
from unittest import mock

import litellm
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info
from litellm.types.utils import LlmProviders
from litellm.utils import ProviderConfigManager
from src.shared.litellm_model_names import (
    SAMPLING_PARAMETERS,
    litellm_call_model,
    litellm_lookup_name,
    litellm_model_capability,
    litellm_refuses_sampling,
)

from ai_models.domain.specs import ModelKind, ModelSpec
from ai_models.utils.litellm_model_info import reasoning_support

_KIND_BY_MODE = {
    "chat": ModelKind.LLM,
    "embedding": ModelKind.EMBEDDING,
    "audio_transcription": ModelKind.TRANSCRIPTION,
}

# LiteLLM files some models under names that are not providers you can call: each is
# a variant of the provider its models are called through. Every `vertex_ai-<family>`
# name is Vertex AI too.
_PROVIDER_VARIANTS = {
    "cohere_chat": "cohere",
    "bedrock_converse": "bedrock",
    "fireworks_ai-embedding-models": "fireworks_ai",
}
_VERTEX_AI = "vertex_ai"

_LIMIT_KEYS = ("max_input_tokens", "max_output_tokens")


class CatalogSourceError(Exception):
    """LiteLLM could not answer, usually because a release moved an internal API."""


def _provider(litellm_provider: str) -> str:
    if litellm_provider.startswith(f"{_VERTEX_AI}-"):
        return _VERTEX_AI
    return _PROVIDER_VARIANTS.get(litellm_provider, litellm_provider)


def _ask[T](question: str, answer: Callable[[], T]) -> T:
    try:
        return answer()
    except Exception as error:
        raise CatalogSourceError(f"LiteLLM failed to {question}: {error!r}") from error


class LiteLLMAdapter:
    """Read models and their settings from the installed LiteLLM."""

    def version(self) -> str:
        return version("litellm")

    def uses_bundled_model_map(self) -> bool:
        """True when LiteLLM loaded the model map bundled with this release because
        LITELLM_LOCAL_MODEL_COST_MAP told it to, not one fetched from upstream.

        Asked of LiteLLM rather than read from the environment: LiteLLM reads the flag
        once at import and takes only "true", so a value any other parser accepts
        (e.g. "1") would still leave it fetching.
        """
        return _ask(
            "say where its model map came from",
            lambda: bool(get_model_cost_map_source_info()["is_env_forced"]),
        )

    def model_entries(self, kind: ModelKind) -> Iterator[ModelSpec]:
        """Yield every LiteLLM model of `kind`, with `parameter_names` left empty.

        A name is LiteLLM's model-map key as is, the form `LLMModel.name` stores. LiteLLM
        lists some models twice, bare and `<provider>/`-prefixed; one model is kept, under
        the prefixed key, because that is the entry LiteLLM resolves for both.
        """
        return iter(_ask(f"read {kind} models", lambda: self._model_entries(kind)))

    def _model_entries(self, kind: ModelKind) -> list[ModelSpec]:
        keys_by_lookup_name: dict[tuple[str, str], str] = {}
        entries = {}
        for key, entry in sorted(litellm.model_cost.items()):
            if _KIND_BY_MODE.get(entry.get("mode")) != kind:
                continue
            provider = _provider(entry["litellm_provider"])
            lookup_name = (provider, litellm_lookup_name(provider, key))
            kept_key = keys_by_lookup_name.get(lookup_name)
            if kept_key is not None and kept_key == lookup_name[1]:
                continue
            keys_by_lookup_name[lookup_name] = key
            entries.pop(kept_key, None)
            entries[key] = self._model(key, provider, kind, entry)
        return list(entries.values())

    def _model(self, name: str, provider: str, kind: ModelKind, entry: Mapping) -> ModelSpec:
        deprecation_date = entry.get("deprecation_date")
        options = {}
        if kind == ModelKind.LLM:
            efforts = reasoning_support(provider, name).ordered_efforts()
            if efforts:
                options["reasoning_effort"] = tuple(efforts)
        return ModelSpec(
            name=name,
            provider=provider,
            kind=kind,
            recommended=False,
            deprecation_date=date.fromisoformat(deprecation_date) if deprecation_date else None,
            limits={
                limit: entry[limit]
                for limit in _LIMIT_KEYS
                if isinstance(entry.get(limit), int | float) and entry[limit] > 0
            },
            parameter_names=(),
            options=options,
        )

    def llm_parameters(self, model: ModelSpec) -> tuple[str, ...]:
        """Return the settings LiteLLM lets the model take.

        A model LiteLLM refuses sampling for (`litellm_refuses_sampling`) takes no
        sampling setting, even where LiteLLM's supported-parameter list still names one.
        """
        return _ask(f"list the settings of {model.name}", lambda: self._llm_parameters(model))

    def _llm_parameters(self, model: ModelSpec) -> tuple[str, ...]:
        names = tuple(
            litellm.get_supported_openai_params(
                model=model.name, custom_llm_provider=model.provider
            )
            or ()
        )
        if litellm_refuses_sampling(litellm_call_model(model.provider, model.name)):
            return tuple(name for name in names if name not in SAMPLING_PARAMETERS)
        return names

    def supports_adaptive_thinking(self, model: ModelSpec) -> bool:
        return (
            litellm_model_capability(
                litellm_call_model(model.provider, model.name), "supports_adaptive_thinking"
            )
            is True
        )

    def embedding_parameters(self, provider: str) -> tuple[str, ...] | None:
        """Return the provider's embedding settings; None when LiteLLM has no config class.

        Never falls back to LiteLLM's generic call, which answers the chat settings.
        """
        return self._config_parameters(
            provider, "embedding", ProviderConfigManager.get_provider_embedding_config
        )

    def transcription_parameters(self, provider: str) -> tuple[str, ...] | None:
        """Return the provider's transcription settings; None when LiteLLM has no config class."""
        return self._config_parameters(
            provider,
            "transcription",
            ProviderConfigManager.get_provider_audio_transcription_config,
        )

    def _config_parameters(
        self, provider: str, kind_label: str, get_config: Callable
    ) -> tuple[str, ...] | None:
        try:
            litellm_provider = LlmProviders(provider)
        except ValueError:
            # Not a provider LiteLLM has config classes for.
            return None

        def names() -> tuple[str, ...] | None:
            # Per provider, so no model narrows the config LiteLLM picks.
            config = get_config(model="", provider=litellm_provider)
            return None if config is None else tuple(config.get_supported_openai_params(model=""))

        return _ask(f"list the {kind_label} settings of {provider}", names)

    def credential_names(self, model: ModelSpec) -> tuple[str, ...]:
        """Return the environment variables LiteLLM reads the model's credentials from."""

        def names() -> tuple[str, ...]:
            # LiteLLM lists only the variables missing from this process's environment;
            # an empty one makes the answer the same on every machine.
            with mock.patch.dict(os.environ, clear=True):
                result = litellm.validate_environment(
                    model=litellm_lookup_name(model.provider, model.name)
                )
            return tuple(result["missing_keys"])

        return _ask(f"list the credentials of {model.name}", names)

    def completion_annotations(self) -> Mapping[str, object]:
        """Return the type hint of each `litellm.completion` argument that has one."""

        def annotations() -> dict[str, object]:
            # The signature follows `__wrapped__` to the typed function behind LiteLLM's
            # dispatch wrapper; get_type_hints would fail on a forward reference there.
            parameters = inspect.signature(litellm.completion).parameters
            return {
                name: parameter.annotation
                for name, parameter in parameters.items()
                if parameter.annotation is not inspect.Parameter.empty
            }

        return _ask("read the completion signature", annotations)
