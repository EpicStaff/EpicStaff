"""The rules `build_model_catalog --check` runs: one class per rule, so a new rule never edits the checker.

Rules that judge content read the fresh catalog (what the installed LiteLLM and the current
registry produce), so their findings name what to fix in the registry; `CatalogUpToDateRule`
alone compares it with the committed file.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ai_models.domain.catalog import Catalog
from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.specs import ModelKind, ModelSpec

_NUMBER_TYPES = frozenset({"number", "integer"})
_CHOICE_TYPE = "choice"


@dataclass(frozen=True, slots=True)
class CatalogCheckFinding:
    """One problem found by a rule; only errors fail `--check`."""

    rule: str
    message: str
    is_error: bool


class BaseCatalogCheckRule(ABC):
    @abstractmethod
    def check(
        self, committed: Catalog, fresh: Catalog, registry: ParameterRegistry
    ) -> list[CatalogCheckFinding]: ...

    def _error(self, message: str) -> CatalogCheckFinding:
        return CatalogCheckFinding(rule=type(self).__name__, message=message, is_error=True)


class NoDraftParametersRule(BaseCatalogCheckRule):
    def check(self, committed, fresh, registry):
        return [
            self._error(
                f"{name}: reported by LiteLLM, but not in parameter_registry.yaml; "
                "add it under parameters or hidden."
            )
            for name, spec in fresh.parameters.items()
            if spec.draft
        ]


class NumberRangeRequiredRule(BaseCatalogCheckRule):
    """A number needs a minimum and a maximum, or a model limit that gives the maximum.

    Drafts are left to `NoDraftParametersRule`: none of them has a range.
    """

    def check(self, committed, fresh, registry):
        return [
            self._error(f"{name}: a number needs minimum and maximum (or limit_from).")
            for name, spec in fresh.parameters.items()
            if spec.value_type in _NUMBER_TYPES
            and not spec.draft
            and (spec.minimum is None or (spec.maximum is None and spec.limit_from is None))
        ]


class ChoiceOptionsRequiredRule(BaseCatalogCheckRule):
    """A choice needs options. Drafts are left to `NoDraftParametersRule`."""

    def check(self, committed, fresh, registry):
        return [
            self._error(f"{name}: a choice needs options.")
            for name, spec in fresh.parameters.items()
            if spec.value_type == _CHOICE_TYPE and not spec.draft and not spec.options
        ]


class CatalogUpToDateRule(BaseCatalogCheckRule):
    def check(self, committed, fresh, registry):
        if committed == fresh:
            return []
        return [
            self._error(
                f"catalog.json differs from what LiteLLM {fresh.litellm_version} and "
                "parameter_registry.yaml produce; run build_model_catalog."
            )
        ]


class ConnectionFieldsRequiredRule(BaseCatalogCheckRule):
    """A provider the runtime can run needs connection fields, because LiteLLM's are incomplete."""

    def check(self, committed, fresh, registry):
        return [
            self._error(
                f"{name}: runs {', '.join(provider.kinds)}, but declares no connection_fields."
            )
            for name, provider in fresh.providers.items()
            if provider.kinds and not provider.connection_fields
        ]


class UnusedRegistryEntryRule(BaseCatalogCheckRule):
    """Warn about registry providers and `default_thinking` entries LiteLLM has no model of.

    They may be renamed or gone.
    """

    def check(self, committed, fresh, registry):
        providers_with_models = {
            provider for by_provider in fresh.models.values() for provider in by_provider
        }
        classified_base_names = {
            registry.thinking_base_name(model_name)
            for by_name in fresh.models.get(ModelKind.LLM, {}).values()
            for model_name in by_name
        }
        unused = [
            provider.name
            for provider in registry.providers()
            if provider.name not in providers_with_models
        ] + sorted(registry.thinking_base_names() - classified_base_names)
        return [
            CatalogCheckFinding(
                rule=type(self).__name__,
                message=f"{name}: in parameter_registry.yaml, but LiteLLM has no model of it.",
                is_error=False,
            )
            for name in unused
        ]


class _AdaptiveThinkingSource(Protocol):
    def supports_adaptive_thinking(self, model: ModelSpec) -> bool: ...


class UnclassifiedThinkingModelRule(BaseCatalogCheckRule):
    """A model LiteLLM says thinks adaptively needs a `default_thinking` entry.

    LiteLLM does not say whether such a model thinks when no thinking setting is sent,
    nor how to turn that off, so without an entry "none" may silently leave it thinking.
    Asks LiteLLM through `source`. Only models of registry providers are checked: no
    config can use the others.
    """

    def __init__(self, source: _AdaptiveThinkingSource) -> None:
        self._source = source

    def check(self, committed, fresh, registry):
        llm_models = fresh.models.get(ModelKind.LLM, {})
        return [
            self._error(
                f"{model.name}: LiteLLM says it thinks adaptively, but no default_thinking "
                "entry in parameter_registry.yaml classifies it; add one."
            )
            for provider in fresh.providers
            for model in llm_models.get(provider, {}).values()
            if registry.thinking_base_name(model.name) is None
            and self._source.supports_adaptive_thinking(model)
        ]


class CatalogChecker:
    """Run every rule and collect their findings, in rule order."""

    def __init__(self, rules: Sequence[BaseCatalogCheckRule]) -> None:
        self._rules = rules

    def run(
        self, committed: Catalog, fresh: Catalog, registry: ParameterRegistry
    ) -> list[CatalogCheckFinding]:
        return [
            finding for rule in self._rules for finding in rule.check(committed, fresh, registry)
        ]
