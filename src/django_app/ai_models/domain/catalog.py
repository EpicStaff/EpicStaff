"""The generated model catalog and its JSON file format."""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date

from ai_models.domain.specs import (
    ConnectionFieldSpec,
    DefaultThinkingSpec,
    ModelKind,
    ModelSpec,
    ParameterSpec,
    ProviderSpec,
)


@dataclass(frozen=True, slots=True)
class Catalog:
    """Every parameter, provider and model, as generated from LiteLLM and the registry.

    `models` is keyed by kind, then provider, then model name. Models refer to parameters
    by name, so each `ParameterSpec` is stored once.
    """

    litellm_version: str
    parameters: Mapping[str, ParameterSpec]
    providers: Mapping[str, ProviderSpec]
    models: Mapping[ModelKind, Mapping[str, Mapping[str, ModelSpec]]]

    def to_json(self) -> str:
        """Return the catalog file's text: sorted keys and 2-space indent, so diffs stay small."""
        data = {
            "litellm_version": self.litellm_version,
            "parameters": {
                name: _without(asdict(spec), "name") for name, spec in self.parameters.items()
            },
            "providers": {
                name: _without(asdict(spec), "name") for name, spec in self.providers.items()
            },
            "models": {
                kind: {
                    provider: {
                        model_name: _model_to_dict(model) for model_name, model in models.items()
                    }
                    for provider, models in providers.items()
                }
                for kind, providers in self.models.items()
            },
        }
        return json.dumps(data, sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Catalog":
        data = json.loads(text)
        return cls(
            litellm_version=data["litellm_version"],
            parameters={
                name: _parameter_from_dict(name, fields)
                for name, fields in data["parameters"].items()
            },
            providers={
                name: _provider_from_dict(name, fields)
                for name, fields in data["providers"].items()
            },
            models={
                ModelKind(kind): {
                    provider: {
                        model_name: _model_from_dict(model_name, provider, ModelKind(kind), fields)
                        for model_name, fields in models.items()
                    }
                    for provider, models in providers.items()
                }
                for kind, providers in data["models"].items()
            },
        )


def _without(fields: dict, *names: str) -> dict:
    return {key: value for key, value in fields.items() if key not in names}


def _model_to_dict(model: ModelSpec) -> dict:
    # Name, provider and kind are the keys the model is stored under.
    fields = _without(asdict(model), "name", "provider", "kind")
    if model.deprecation_date is not None:
        fields["deprecation_date"] = model.deprecation_date.isoformat()
    # Written only where set: few models think by default, and a null on every other
    # model would only grow the file.
    if model.default_thinking is None:
        del fields["default_thinking"]
    return fields


def _parameter_from_dict(name: str, fields: dict) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        **{
            **fields,
            "options": tuple(fields["options"]),
            "overrides": {
                provider: {
                    field: tuple(value) if field == "options" else value
                    for field, value in replacements.items()
                }
                for provider, replacements in fields["overrides"].items()
            },
        },
    )


def _provider_from_dict(name: str, fields: dict) -> ProviderSpec:
    return ProviderSpec(
        name=name,
        label=fields["label"],
        recommended=fields["recommended"],
        kinds=tuple(ModelKind(kind) for kind in fields["kinds"]),
        custom_models=fields["custom_models"],
        connection_fields=tuple(
            ConnectionFieldSpec(**field) for field in fields["connection_fields"]
        ),
        common_parameters={
            ModelKind(kind): tuple(names) for kind, names in fields["common_parameters"].items()
        },
        aliases=tuple(fields["aliases"]),
        main_secret_argument=fields["main_secret_argument"],
    )


def _model_from_dict(name: str, provider: str, kind: ModelKind, fields: dict) -> ModelSpec:
    deprecation_date = fields["deprecation_date"]
    default_thinking = fields.get("default_thinking")
    return ModelSpec(
        name=name,
        provider=provider,
        kind=kind,
        recommended=fields["recommended"],
        deprecation_date=date.fromisoformat(deprecation_date) if deprecation_date else None,
        limits=fields["limits"],
        parameter_names=tuple(fields["parameter_names"]),
        options={setting: tuple(values) for setting, values in fields["options"].items()},
        default_thinking=DefaultThinkingSpec(**default_thinking) if default_thinking else None,
    )
