from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import jsonschema
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for

from app.exceptions import InvalidOutputSchemaError
from shared.models.agent_service import TokenUsage


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    parsed: dict | None = None
    error: str | None = None


def as_object_schema(schema: dict) -> tuple[dict, bool]:
    """Tool input schemas must be type:object. Wrap non-object schemas under 'result'.

    Raises ``InvalidOutputSchemaError`` if ``schema`` is not a dict or lacks a
    top-level "type" key — e.g. a bare field map saved instead of a full JSON
    Schema. Such shapes cannot be recognized as either an object schema or a
    scalar/array schema to wrap, so there is nothing safe to enforce against.
    """
    if not isinstance(schema, dict) or "type" not in schema:
        raise InvalidOutputSchemaError(
            f'output_schema must be a JSON Schema with a top-level "type" key, '
            f"got: {schema!r}. If this was built from a field list, wrap it as "
            f'{{"type": "object", "properties": {{...}}, "required": [...]}}.'
        )

    if schema.get("type") == "object":
        return schema, False

    return {
        "type": "object",
        "properties": {"result": schema},
        "required": ["result"],
    }, True


@lru_cache(maxsize=128)
def _validator(schema_json: str):
    schema = json.loads(schema_json)
    cls = validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def validate_output(obj, schema: dict) -> ValidationOutcome:
    # Same steps as jsonschema.validate, with the checked validator cached per schema.
    try:
        validator = _validator(json.dumps(schema, sort_keys=True))

    except jsonschema.exceptions.SchemaError as error:
        raise InvalidOutputSchemaError(
            f"output_schema is not a valid JSON Schema: {error.message}"
        ) from error

    error = best_match(validator.iter_errors(obj))

    if error is not None:
        return ValidationOutcome(ok=False, error=error.message)

    return ValidationOutcome(ok=True, parsed=obj)


def add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        cached_prompt_tokens=a.cached_prompt_tokens + b.cached_prompt_tokens,
        total_cost_usd=a.total_cost_usd + b.total_cost_usd,
    )
