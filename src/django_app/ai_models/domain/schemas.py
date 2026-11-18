"""JSON Schemas of a config's `parameters` and `connection`, built from the catalog.

The frontend renders the config form from these schemas and the backend validates with
the same ones, so the two cannot disagree.
"""

import functools
from typing import Protocol

from ai_models.domain.specs import (
    ConnectionFieldSpec,
    ModelKind,
    ModelSpec,
    ParameterSpec,
    ProviderSpec,
)
from ai_models.domain.value_types import ValueTypeRegistry

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SECRET_MARKER_PATTERN = r"^epicstaff_secret\(\s*[^)]+?\s*\)$"
# Model names come from request query strings, so the memo must not grow without bound.
_MEMO_SIZE = 1024


class _CatalogLookup(Protocol):
    def model(self, kind: ModelKind, provider: str, name: str) -> ModelSpec | None: ...

    def provider(self, name: str) -> ProviderSpec | None: ...

    def parameter(self, name: str, provider: str) -> ParameterSpec: ...

    def parameter_names(
        self, kind: ModelKind, provider: str, model_name: str
    ) -> tuple[str, ...]: ...


class ConfigSchemaFactory:
    """Build the draft 2020-12 schemas of a config, once per argument tuple.

    Both schemas reject keys they do not list (`additionalProperties: false`). A schema
    is shared by every caller asking for the same arguments: never modify one.
    """

    def __init__(self, repository: _CatalogLookup, value_types: ValueTypeRegistry) -> None:
        self._repository = repository
        self._value_types = value_types
        self._parameters_schema = functools.lru_cache(_MEMO_SIZE)(self._build_parameters_schema)
        self._connection_schema = functools.lru_cache(_MEMO_SIZE)(self._build_connection_schema)

    def parameters_schema(self, kind: ModelKind, provider: str, model_name: str) -> dict:
        """Return the schema of the settings a config of this model may hold, with UI hints."""
        return self._parameters_schema(kind, provider, model_name)

    def connection_schema(self, provider: str) -> dict:
        """Return the schema of `provider`'s connection fields; secret fields take only a marker."""
        return self._connection_schema(provider)

    def _build_parameters_schema(self, kind: ModelKind, provider: str, model_name: str) -> dict:
        model = self._repository.model(kind, provider, model_name)
        properties = {}
        for name in self._repository.parameter_names(kind, provider, model_name):
            spec = self._repository.parameter(name, provider)
            properties[name] = self._value_types.get(spec.value_type).schema_fragment(spec, model)
        return _object_schema(properties, required=[])

    def _build_connection_schema(self, provider: str) -> dict:
        provider_spec = self._repository.provider(provider)
        fields = provider_spec.connection_fields if provider_spec else ()
        return _object_schema(
            {field.name: _connection_fragment(field) for field in fields},
            required=[field.name for field in fields if field.required],
        )


def _object_schema(properties: dict, required: list[str]) -> dict:
    schema = {
        "$schema": _DRAFT_2020_12,
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _connection_fragment(field: ConnectionFieldSpec) -> dict:
    # Connection values are strings on the wire: they become LiteLLM keyword arguments.
    fragment = {"type": "string", "title": field.label, "x-widget": field.control}
    if field.secret:
        fragment.update({"x-widget": "secret", "pattern": _SECRET_MARKER_PATTERN})
    elif field.required:
        fragment["minLength"] = 1
    return fragment
