"""The hand-written parameter registry: what LiteLLM does not say about settings and providers."""

from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

import yaml

from ai_models.domain.specs import ConnectionFieldSpec, ModelKind, ParameterSpec, ProviderSpec
from ai_models.domain.value_types import ValueTypeRegistry

_TOP_LEVEL_KEYS = frozenset(
    {"parameters", "hidden", "providers", "kind_parameters", "recommended_models"}
)
_CONTROLS = frozenset(
    {"slider", "percent", "stepper", "toggle", "select", "chips", "list", "json", "text"}
)

_PARAMETER_REQUIRED = frozenset({"value_type", "control", "label", "help_text", "group", "default"})
_PARAMETER_OPTIONAL = {
    "minimum": None,
    "maximum": None,
    "step": None,
    "options": (),
    "limit_from": None,
    "overrides": {},
}
_OVERRIDABLE = (_PARAMETER_REQUIRED | frozenset(_PARAMETER_OPTIONAL)) - {"overrides"}

_PROVIDER_REQUIRED = frozenset({"label", "kinds"})
_PROVIDER_OPTIONAL = {
    "recommended": False,
    "custom_models": False,
    "connection_fields": {},
    "common_parameters": {},
    "aliases": [],
    "main_secret_argument": "api_key",
}

_CONNECTION_FIELD_REQUIRED = frozenset({"label", "litellm_argument"})
_CONNECTION_FIELD_OPTIONAL = {
    "value_type": "text",
    "control": "text",
    "required": False,
    "secret": False,
    "endpoint": False,
}


class ParameterRegistry:
    """Read-only view of `parameter_registry.yaml`.

    Loading rejects unknown keys at every level and names that point nowhere, because a
    typo must not silently drop a limit or a provider.
    """

    def __init__(
        self,
        *,
        parameters: Mapping[str, ParameterSpec],
        providers: Mapping[str, ProviderSpec],
        hidden_names: frozenset[str],
        kind_parameters: Mapping[ModelKind, Mapping[str, tuple[str, ...]]],
        recommended_models: Mapping[str, frozenset[str]],
    ) -> None:
        self._parameters = parameters
        self._providers = providers
        self.hidden_names = hidden_names
        self._kind_parameters = kind_parameters
        self._recommended_models = recommended_models

    @classmethod
    def load(cls, path: Path) -> "ParameterRegistry":
        """Load and check a registry file.

        Raises:
            ValueError: The file has an unknown key, misses a required one, or names a
                parameter, provider, kind, value type or control that does not exist.
        """
        data = _with_defaults(yaml.safe_load(path.read_text()), _TOP_LEVEL_KEYS, {}, "registry")
        provider_names = frozenset(_mapping(data["providers"], "providers"))
        parameters = {
            name: _parameter(name, fields, provider_names)
            for name, fields in _mapping(data["parameters"], "parameters").items()
        }
        hidden_names = frozenset(data["hidden"])
        declared_twice = hidden_names & parameters.keys()
        if declared_twice:
            raise ValueError(f"hidden: also parameters: {', '.join(sorted(declared_twice))}")
        recommended_models = _mapping(data["recommended_models"], "recommended_models")
        _check_known(recommended_models, provider_names, "recommended_models")
        providers = {
            name: _provider(name, fields, parameters) for name, fields in data["providers"].items()
        }
        _check_aliases(providers)
        return cls(
            parameters=parameters,
            providers=providers,
            hidden_names=hidden_names,
            kind_parameters=_kind_parameters(data["kind_parameters"], provider_names, parameters),
            recommended_models={
                provider: frozenset(models) for provider, models in recommended_models.items()
            },
        )

    def parameter(self, name: str) -> ParameterSpec | None:
        return self._parameters.get(name)

    def providers(self) -> tuple[ProviderSpec, ...]:
        return tuple(self._providers.values())

    def provider(self, name: str) -> ProviderSpec | None:
        return self._providers.get(name)

    def kind_parameters(self, kind: ModelKind, provider: str) -> tuple[str, ...] | None:
        """Return the settings the registry declares for every `kind` model of `provider`.

        None means the registry declares none, so they are discovered from LiteLLM.
        """
        return self._kind_parameters.get(kind, {}).get(provider)

    def is_recommended(self, provider: str, model: str) -> bool:
        return model in self._recommended_models.get(provider, frozenset())


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        # ValueError like every other registry problem, so callers handle one error type.
        raise ValueError(f"{where}: must be a mapping")  # noqa: TRY004
    return value


def _check_keys(value: object, required: frozenset[str], allowed: Collection[str], where: str):
    mapping = _mapping(value, where)
    unknown = mapping.keys() - required - set(allowed)
    if unknown:
        raise ValueError(f"{where}: unknown key(s): {', '.join(sorted(unknown))}")
    missing = required - mapping.keys()
    if missing:
        raise ValueError(f"{where}: missing key(s): {', '.join(sorted(missing))}")
    return mapping


def _with_defaults(value: object, required: frozenset[str], optional: dict, where: str) -> dict:
    return {**optional, **_check_keys(value, required, optional, where)}


def _check_known(names: Iterable[str], known_names: Collection[str], where: str) -> None:
    unknown = [name for name in names if name not in known_names]
    if unknown:
        raise ValueError(f"{where}: unknown name(s): {', '.join(unknown)}")


def _kind(value: str, where: str) -> ModelKind:
    try:
        return ModelKind(value)
    except ValueError:
        raise ValueError(f"{where}: unknown kind: {value}") from None


def _check_type_and_control(fields: Mapping, where: str) -> None:
    if "value_type" in fields:
        try:
            ValueTypeRegistry().get(fields["value_type"])
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
    if "control" in fields and fields["control"] not in _CONTROLS:
        raise ValueError(f"{where}: unknown control: {fields['control']}")


def _parameter(name: str, value: object, provider_names: frozenset[str]) -> ParameterSpec:
    where = f"parameters.{name}"
    fields = _with_defaults(value, _PARAMETER_REQUIRED, _PARAMETER_OPTIONAL, where)
    _check_type_and_control(fields, where)
    overrides = {}
    for provider, replacements in _mapping(fields["overrides"], f"{where}.overrides").items():
        override_where = f"{where}.overrides.{provider}"
        _check_keys(replacements, frozenset(), _OVERRIDABLE, override_where)
        _check_known([provider], provider_names, f"{where}.overrides")
        _check_type_and_control(replacements, override_where)
        overrides[provider] = {
            field: tuple(replacement) if field == "options" else replacement
            for field, replacement in replacements.items()
        }
    return ParameterSpec(
        name=name,
        **{**fields, "options": tuple(fields["options"]), "overrides": overrides},
        draft=False,
    )


def _provider(name: str, value: object, parameters: Mapping[str, ParameterSpec]) -> ProviderSpec:
    where = f"providers.{name}"
    fields = _with_defaults(value, _PROVIDER_REQUIRED, _PROVIDER_OPTIONAL, where)
    connection_fields = []
    for field_name, field_value in _mapping(
        fields["connection_fields"], f"{where}.connection_fields"
    ).items():
        field_where = f"{where}.connection_fields.{field_name}"
        field = _with_defaults(
            field_value, _CONNECTION_FIELD_REQUIRED, _CONNECTION_FIELD_OPTIONAL, field_where
        )
        _check_type_and_control(field, field_where)
        connection_fields.append(ConnectionFieldSpec(name=field_name, **field))
    common_parameters = {}
    for kind, names in _mapping(fields["common_parameters"], f"{where}.common_parameters").items():
        kind_where = f"{where}.common_parameters.{kind}"
        _check_known(names, parameters, kind_where)
        common_parameters[_kind(kind, kind_where)] = tuple(names)
    return ProviderSpec(
        name=name,
        label=fields["label"],
        recommended=fields["recommended"],
        kinds=tuple(_kind(kind, f"{where}.kinds") for kind in fields["kinds"]),
        custom_models=fields["custom_models"],
        connection_fields=tuple(connection_fields),
        common_parameters=common_parameters,
        aliases=tuple(fields["aliases"]),
        main_secret_argument=fields["main_secret_argument"],
    )


def _check_aliases(providers: Mapping[str, ProviderSpec]) -> None:
    # An alias resolves to exactly one provider, so it may not be any other name.
    taken = set(providers)
    for provider in providers.values():
        for alias in provider.aliases:
            if alias in taken:
                raise ValueError(
                    f"providers.{provider.name}.aliases: {alias} is already a provider name or alias"
                )
            taken.add(alias)


def _kind_parameters(
    value: object, provider_names: frozenset[str], parameters: Mapping[str, ParameterSpec]
) -> dict[ModelKind, dict[str, tuple[str, ...]]]:
    kind_parameters = {}
    for kind, by_provider in _mapping(value, "kind_parameters").items():
        kind_where = f"kind_parameters.{kind}"
        by_provider = _mapping(by_provider, kind_where)
        _check_known(by_provider, provider_names, kind_where)
        for provider, names in by_provider.items():
            _check_known(names, parameters, f"{kind_where}.{provider}")
        kind_parameters[_kind(kind, kind_where)] = {
            provider: tuple(names) for provider, names in by_provider.items()
        }
    return kind_parameters
