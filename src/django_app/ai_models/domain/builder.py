"""Assemble the model catalog from LiteLLM's models, the discovery strategies and the registry."""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Protocol

from ai_models.domain.catalog import Catalog
from ai_models.domain.discovery import BaseParameterDiscoveryStrategy
from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.specs import ModelKind, ModelSpec, ParameterSpec
from ai_models.domain.value_types import ValueTypeRegistry

# A draft has no range or options, so it gets a control that works without them.
_DRAFT_CONTROLS = {
    "number": "stepper",
    "integer": "stepper",
    "boolean": "toggle",
    "choice": "select",
    "text": "text",
    "text_list": "list",
    "json": "json",
}


class _ModelSource(Protocol):
    def version(self) -> str: ...

    def model_entries(self, kind: ModelKind) -> Iterator[ModelSpec]: ...

    def completion_annotations(self) -> Mapping[str, object]: ...


class CatalogBuilder:
    """Build the catalog: every model LiteLLM knows, with the settings each one takes.

    The catalog holds the registry's settings that a model or a provider's custom-model
    list uses, plus a draft for every setting LiteLLM reports that the registry lacks.
    Only registry providers get a `ProviderSpec`; models of other providers are kept
    under their provider name with none.
    """

    def __init__(
        self,
        adapter: _ModelSource,
        registry: ParameterRegistry,
        strategies: Sequence[BaseParameterDiscoveryStrategy],
        value_types: ValueTypeRegistry,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._strategies = {strategy.kind: strategy for strategy in strategies}
        self._value_types = value_types

    def build(self) -> Catalog:
        models = {}
        for kind in ModelKind:
            by_provider = {}
            for model in self._adapter.model_entries(kind):
                by_provider.setdefault(model.provider, {})[model.name] = replace(
                    model,
                    recommended=self._registry.is_recommended(model.provider, model.name),
                    parameter_names=self._strategies[kind].discover(model),
                )
            if by_provider:
                models[kind] = by_provider
        providers = {provider.name: provider for provider in self._registry.providers()}
        annotations = self._adapter.completion_annotations()
        parameters = {
            name: self._registry.parameter(name) or self._draft(name, annotations.get(name))
            for name in sorted(_used_parameter_names(models, providers))
        }
        return Catalog(
            litellm_version=self._adapter.version(),
            parameters=parameters,
            providers=providers,
            models=models,
        )

    def _draft(self, name: str, annotation: object) -> ParameterSpec:
        value_type = self._value_types.guess(annotation).name
        return ParameterSpec(
            name=name,
            value_type=value_type,
            control=_DRAFT_CONTROLS[value_type],
            label=name.replace("_", " ").capitalize(),
            help_text="Reported by LiteLLM, not yet described in parameter_registry.yaml.",
            group="advanced",
            default=None,
            minimum=None,
            maximum=None,
            step=None,
            options=(),
            limit_from=None,
            draft=True,
            overrides={},
        )

    @staticmethod
    def changes(previous: Catalog | None, current: Catalog) -> list[str]:
        """Return the summary lines of what `current` changes against `previous` (None: no file yet)."""
        previous_models = _model_keys(previous) if previous else set()
        current_models = _model_keys(current)
        previous_parameters = set(previous.parameters) if previous else set()
        current_parameters = set(current.parameters)
        drafts = [name for name, spec in current.parameters.items() if spec.draft]
        return [
            f"models added: {len(current_models - previous_models)}",
            f"models removed: {len(previous_models - current_models)}",
            f"settings appeared: {_listed(current_parameters - previous_parameters)}",
            f"settings disappeared: {_listed(previous_parameters - current_parameters)}",
            f"drafts waiting: {_listed(drafts)}",
        ]


def _used_parameter_names(models: Mapping, providers: Mapping) -> set[str]:
    reported = {
        name
        for by_provider in models.values()
        for by_name in by_provider.values()
        for model in by_name.values()
        for name in model.parameter_names
    }
    offered_for_custom_models = {
        name
        for provider in providers.values()
        for names in provider.common_parameters.values()
        for name in names
    }
    return reported | offered_for_custom_models


def _model_keys(catalog: Catalog) -> set[tuple[ModelKind, str, str]]:
    return {
        (kind, provider, name)
        for kind, by_provider in catalog.models.items()
        for provider, by_name in by_provider.items()
        for name in by_name
    }


def _listed(names: Iterable[str]) -> str:
    return ", ".join(sorted(names)) or "none"
