from __future__ import annotations

from dataclasses import dataclass

import jsonschema

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


def validate_output(obj, schema: dict) -> ValidationOutcome:
    try:
        jsonschema.validate(obj, schema)
        return ValidationOutcome(ok=True, parsed=obj)

    except jsonschema.ValidationError as error:
        return ValidationOutcome(ok=False, error=error.message)

    except jsonschema.exceptions.SchemaError as error:
        raise InvalidOutputSchemaError(
            f"output_schema is not a valid JSON Schema: {error.message}"
        ) from error


def add_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        cached_prompt_tokens=a.cached_prompt_tokens + b.cached_prompt_tokens,
        total_cost_usd=a.total_cost_usd + b.total_cost_usd,
    )
