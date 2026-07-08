"""Tests for app.output.schema helpers."""

from __future__ import annotations

import pytest

from app.exceptions import InvalidOutputSchemaError
from app.output.schema import add_usage, as_object_schema, validate_output
from shared.models.agent_service import TokenUsage


# ---------------------------------------------------------------------------
# as_object_schema
# ---------------------------------------------------------------------------


def test_as_object_schema_passthrough_for_object_type():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    result, wrapped = as_object_schema(schema)
    assert result is schema
    assert wrapped is False


def test_as_object_schema_wraps_non_object_schema():
    schema = {"type": "string"}
    result, wrapped = as_object_schema(schema)
    assert wrapped is True
    assert result["type"] == "object"
    assert result["properties"]["result"] == schema
    assert result["required"] == ["result"]


def test_as_object_schema_wraps_array_schema():
    schema = {"type": "array", "items": {"type": "integer"}}
    result, wrapped = as_object_schema(schema)
    assert wrapped is True
    assert result["properties"]["result"] == schema


def test_as_object_schema_raises_on_bare_field_map():
    """A bare field map (no top-level 'type') is not a recognizable schema."""
    schema = {"reasoning": {"type": "string", "description": "why"}}

    with pytest.raises(InvalidOutputSchemaError):
        as_object_schema(schema)


def test_as_object_schema_raises_on_dict_without_type():
    schema = {"properties": {"x": {"type": "string"}}}

    with pytest.raises(InvalidOutputSchemaError):
        as_object_schema(schema)


def test_as_object_schema_raises_on_non_dict():
    with pytest.raises(InvalidOutputSchemaError):
        as_object_schema("not-a-schema")


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


def test_add_usage_sums_all_fields():
    a = TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    b = TokenUsage(prompt_tokens=7, completion_tokens=2, total_tokens=9)
    result = add_usage(a, b)
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 5
    assert result.total_tokens == 17


def test_add_usage_with_zero():
    a = TokenUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14)
    b = TokenUsage()
    result = add_usage(a, b)
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 4
    assert result.total_tokens == 14
