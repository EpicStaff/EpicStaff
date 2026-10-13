"""Tests for app.output.schema helpers."""

from __future__ import annotations

import pytest
from app.exceptions import InvalidOutputSchemaError
from app.output.schema import add_usage, as_object_schema, validate_output
from shared.models.agent_service import TokenUsage

# ---------------------------------------------------------------------------
# as_object_schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [{"type": "string"}, {"type": "array", "items": {"type": "integer"}}],
    ids=["string", "array"],
)
def test_non_object_schema_is_wrapped_under_result(schema):
    result, wrapped = as_object_schema(schema)

    assert wrapped is True
    assert (result["type"], result["properties"], result["required"]) == ("object", {"result": schema}, ["result"])


def test_object_schema_is_used_as_is():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    assert as_object_schema(schema) == (schema, False)


@pytest.mark.parametrize(
    "schema",
    [
        # A bare field map has no top-level type, so it is not a recognizable schema.
        {"reasoning": {"type": "string", "description": "why"}},
        {"properties": {"x": {"type": "string"}}},
        "not-a-schema",
    ],
    ids=["bare-field-map", "no-type", "not-a-dict"],
)
def test_unrecognizable_schema_is_refused(schema):
    with pytest.raises(InvalidOutputSchemaError):
        as_object_schema(schema)


# ---------------------------------------------------------------------------
# validate_output
# ---------------------------------------------------------------------------


def test_validate_output_ok_for_valid_data():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    outcome = validate_output({"x": 42}, schema)
    assert outcome.ok is True
    assert outcome.parsed == {"x": 42}
    assert outcome.error is None


def test_validate_output_error_for_invalid_data():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    outcome = validate_output({"x": "not-an-int"}, schema)
    assert outcome.ok is False
    assert outcome.error is not None
    assert len(outcome.error) > 0


def test_validate_output_error_for_missing_required():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    outcome = validate_output({}, schema)
    assert outcome.ok is False
    assert outcome.error is not None


def test_validate_output_raises_invalid_output_schema_error_for_meta_invalid_schema():
    """A schema that fails jsonschema's own meta-validation surfaces as
    InvalidOutputSchemaError instead of an anonymous SchemaError crash."""
    schema = {"type": "object", "properties": "garbage"}

    with pytest.raises(InvalidOutputSchemaError):
        validate_output({"x": 1}, schema)


# ---------------------------------------------------------------------------
# add_usage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (
            TokenUsage(prompt_tokens=7, completion_tokens=2, total_tokens=9, cached_prompt_tokens=1, total_cost_usd=0.002),
            (12, 5, 17, 3, 0.003),
        ),
        (TokenUsage(), (5, 3, 8, 2, 0.001)),
    ],
    ids=["sum", "zero"],
)
def test_add_usage_sums_every_field(other, expected):
    usage = TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8, cached_prompt_tokens=2, total_cost_usd=0.001)

    result = add_usage(usage, other)

    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens, result.cached_prompt_tokens) == expected[:4]
    assert result.total_cost_usd == pytest.approx(expected[4])
