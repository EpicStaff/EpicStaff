"""Which settings each model takes: one discovery strategy per model kind."""

from abc import ABC, abstractmethod
from typing import ClassVar, Protocol

from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.specs import ModelKind, ModelSpec


class _ParameterSource(Protocol):
    def llm_parameters(self, model: ModelSpec) -> tuple[str, ...]: ...

    def embedding_parameters(self, provider: str) -> tuple[str, ...] | None: ...

    def transcription_parameters(self, provider: str) -> tuple[str, ...] | None: ...


class BaseParameterDiscoveryStrategy(ABC):
    """Find the settings a model of `kind` takes; runtime-only names are never settings."""

    kind: ClassVar[ModelKind]

    def __init__(self, adapter: _ParameterSource, registry: ParameterRegistry) -> None:
        self._adapter = adapter
        self._registry = registry

    def discover(self, model: ModelSpec) -> tuple[str, ...]:
        """Return the model's setting names, sorted, without the registry's hidden names."""
        return tuple(sorted(set(self._names(model)) - self._registry.hidden_names))

    @abstractmethod
    def _names(self, model: ModelSpec) -> tuple[str, ...]: ...


class LLMParameterDiscoveryStrategy(BaseParameterDiscoveryStrategy):
    kind = ModelKind.LLM

    def _names(self, model: ModelSpec) -> tuple[str, ...]:
        return self._adapter.llm_parameters(model)


class _RegistryFirstDiscoveryStrategy(BaseParameterDiscoveryStrategy):
    """The registry's list for the provider wins; LiteLLM answers only where it has none.

    LiteLLM has no per-model discovery for these kinds, so its answer is per provider.
    """

    def _names(self, model: ModelSpec) -> tuple[str, ...]:
        declared = self._registry.kind_parameters(self.kind, model.provider)
        if declared is not None:
            return declared
        return self._litellm_names(model.provider) or ()

    @abstractmethod
    def _litellm_names(self, provider: str) -> tuple[str, ...] | None: ...


class EmbeddingParameterDiscoveryStrategy(_RegistryFirstDiscoveryStrategy):
    kind = ModelKind.EMBEDDING

    def _litellm_names(self, provider: str) -> tuple[str, ...] | None:
        return self._adapter.embedding_parameters(provider)


class TranscriptionParameterDiscoveryStrategy(_RegistryFirstDiscoveryStrategy):
    kind = ModelKind.TRANSCRIPTION

    def _litellm_names(self, provider: str) -> tuple[str, ...] | None:
        return self._adapter.transcription_parameters(provider)
