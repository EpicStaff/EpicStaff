"""Read-only access to the model catalog at run time."""

import functools
from datetime import UTC, datetime
from pathlib import Path

from src.shared.litellm_model_names import litellm_lookup_name

from ai_models.domain.catalog import Catalog
from ai_models.domain.specs import ModelKind, ModelSpec, ParameterSpec, ProviderSpec

_CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"


class CatalogRepository:
    """The one lookup point for providers, models and settings of the catalog.

    Only providers with a `ProviderSpec` are known: the catalog also stores models of
    providers the registry does not list, and those behave as an unknown provider. Every
    lookup by provider name also takes a provider's alias, the name a database
    `Provider` row may use for it, and every lookup by model name matches the name the
    way LiteLLM looks it up (`litellm_lookup_name`), so a stored `anthropic/claude-x`
    finds the catalog's `claude-x` and a stored `gemini-x` finds `gemini/gemini-x`.
    """

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._provider_by_alias = {
            alias: provider.name
            for provider in catalog.providers.values()
            for alias in provider.aliases
        }
        self._models_by_lookup_name: dict[tuple[ModelKind, str], dict[str, ModelSpec]] = {}

    @classmethod
    @functools.cache
    def default(cls) -> "CatalogRepository":
        """Return the repository of the committed `catalog.json`, loaded once per process."""
        return cls(Catalog.from_json(_CATALOG_PATH.read_text()))

    def providers(self, kind: ModelKind) -> list[ProviderSpec]:
        """Return the providers a user can pick for `kind`, recommended first, then by label.

        A provider is offered when it runs `kind` and has a model of that kind to offer,
        or takes custom model names.
        """
        offered = [
            provider
            for provider in self._catalog.providers.values()
            if kind in provider.kinds
            and (provider.custom_models or any(self._offered_models(kind, provider.name)))
        ]
        return sorted(
            offered, key=lambda provider: (not provider.recommended, provider.label.casefold())
        )

    def models(
        self, kind: ModelKind, provider: str, search: str = "", include_deprecated: bool = False
    ) -> list[ModelSpec]:
        """Return `provider`'s models of `kind`, recommended first, then by name.

        `search` matches part of the name, ignoring case. Models past their deprecation
        date are left out unless `include_deprecated`.
        """
        provider = self._resolve(provider)
        models = (
            self._all_models(kind, provider)
            if include_deprecated
            else self._offered_models(kind, provider)
        )
        search = search.lower()
        return sorted(
            (model for model in models if search in model.name.lower()),
            key=lambda model: (not model.recommended, model.name),
        )

    def model(self, kind: ModelKind, provider: str, name: str) -> ModelSpec | None:
        """Return the model, deprecated or not; None when the catalog does not know it.

        `name` may be the catalog key or any name LiteLLM resolves to the same model.
        """
        provider = self._resolve(provider)
        if provider not in self._catalog.providers:
            return None
        models = self._catalog.models.get(kind, {}).get(provider, {})
        if name in models:
            return models[name]
        return self._lookup_index(kind, provider, models).get(litellm_lookup_name(provider, name))

    def provider(self, name: str) -> ProviderSpec | None:
        return self._catalog.providers.get(self._resolve(name))

    def parameter(self, name: str, provider: str) -> ParameterSpec:
        """Return the setting `name` as it applies to `provider`."""
        return self._catalog.parameters[name].for_provider(self._resolve(provider))

    def parameter_names(self, kind: ModelKind, provider: str, model_name: str) -> tuple[str, ...]:
        """Return the settings a `kind` config of `provider` and `model_name` may hold.

        A model the catalog does not know, or one whose provider no longer runs `kind`,
        gets the provider's common list, as a custom model does.
        """
        provider_spec = self.provider(provider)
        if provider_spec is None:
            return ()
        model = self.model(kind, provider, model_name)
        if model is not None and kind in provider_spec.kinds:
            return model.parameter_names
        return provider_spec.common_parameters.get(kind, ())

    def _lookup_index(
        self, kind: ModelKind, provider: str, models: dict[str, ModelSpec]
    ) -> dict[str, ModelSpec]:
        key = (kind, provider)
        if key not in self._models_by_lookup_name:
            self._models_by_lookup_name[key] = {
                litellm_lookup_name(provider, name): model for name, model in models.items()
            }
        return self._models_by_lookup_name[key]

    def _resolve(self, provider: str) -> str:
        return self._provider_by_alias.get(provider, provider)

    def _all_models(self, kind: ModelKind, provider: str):
        if provider not in self._catalog.providers:
            return iter(())
        return iter(self._catalog.models.get(kind, {}).get(provider, {}).values())

    def _offered_models(self, kind: ModelKind, provider: str):
        today = datetime.now(UTC).date()
        return (
            model
            for model in self._all_models(kind, provider)
            if model.deprecation_date is None or model.deprecation_date >= today
        )
