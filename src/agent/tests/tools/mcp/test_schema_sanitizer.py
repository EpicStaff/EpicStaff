"""An external MCP server's input schema reaches the model with control characters
removed and text capped at 1024 characters; keys and enum/const values are refused
rather than changed, since the model's arguments are sent back to the server under
exactly those names and values."""

from __future__ import annotations

import copy

import pytest

from app.tools.mcp.schema_sanitizer import UnsafeSchemaError, sanitize_input_schema

REALISTIC_SCHEMA = {
    "type": "object",
    "title": "Search arguments",
    "properties": {
        "query": {"type": "string", "description": "What to search for.", "minLength": 1},
        "email": {"type": "string", "format": "email", "pattern": "^[^@]+@[^@]+$"},
        "region": {"type": "string", "enum": ["eu", "us"], "default": "eu"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "safe": {"type": "boolean", "default": True},
        "filter": {"$ref": "#/$defs/Filter"},
        "anything": True,
    },
    "required": ["query"],
    "$defs": {
        "Filter": {
            "type": "object",
            "properties": {"site": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        },
    },
}


def test_clean_schema_is_returned_unchanged():
    assert sanitize_input_schema(REALISTIC_SCHEMA) == REALISTIC_SCHEMA


def test_control_characters_are_removed_from_every_string():
    schema = {
        "type": "object",
        "title": "Se\x1b[31march",
        "properties": {
            "query": {"type": "string", "description": "What\x07 to\x00 search\n for."},
            "region": {"type": "string", "default": "e\x7fu", "x-note": "Mind\x1b the gap"},
            "tags": {"type": "array", "items": {"type": "string", "description": "A\ttag."}},
            "email": {"type": "string", "pattern": "^\x07[a-z]+$"},
        },
        "$defs": {"Filter": {"type": "object", "description": "Narrow\x1b the results."}},
    }

    assert sanitize_input_schema(schema) == {
        "type": "object",
        "title": "Se[31march",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "region": {"type": "string", "default": "eu", "x-note": "Mind the gap"},
            "tags": {"type": "array", "items": {"type": "string", "description": "Atag."}},
            "email": {"type": "string", "pattern": "^[a-z]+$"},
        },
        "$defs": {"Filter": {"type": "object", "description": "Narrow the results."}},
    }


def test_text_is_capped_in_any_field():
    schema = {
        "type": "object",
        "$comment": "c" * 2000,
        "properties": {
            "query": {"type": "string", "description": "d" * 2000, "x-note": "n" * 2000},
        },
    }

    sanitized = sanitize_input_schema(schema)

    assert sanitized["$comment"] == "c" * 1024
    assert sanitized["properties"]["query"]["description"] == "d" * 1024
    assert sanitized["properties"]["query"]["x-note"] == "n" * 1024


def test_values_that_cannot_be_cut_are_kept_whole_up_to_the_cap():
    schema = {
        "type": "object",
        "properties": {
            "k" * 1024: {"type": "string", "pattern": "p" * 1024, "enum": ["e" * 1024]},
        },
        "required": ["k" * 1024],
    }

    assert sanitize_input_schema(schema) == schema


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"k" * 1025: {"type": "string"}}},
        {"type": "object", "properties": {"q": {"type": "string", "pattern": "p" * 1025}}},
        {"type": "object", "x-note": {"pattern": "p" * 1025}},
        {"type": "object", "x-note": {"enum": ["e" * 1025]}},
        {"type": "object", "properties": {"q": {"const": "c" * 1025}}},
        {"type": "object", "required": ["r" * 1025]},
        {"type": "object", "$id": "i" * 1025},
    ],
    ids=["key", "pattern", "pattern-in-extension", "enum-in-extension", "const", "required", "id"],
)
def test_a_value_that_cannot_be_cut_is_refused_when_longer_than_the_cap(schema):
    with pytest.raises(UnsafeSchemaError, match="is longer than 1024 characters"):
        sanitize_input_schema(schema)


@pytest.mark.parametrize("name_map", ["properties", "dependencies"])
@pytest.mark.parametrize("parameter_name", ["enum", "const"])
def test_a_parameter_named_like_an_exact_keyword_is_cleaned_as_a_schema(name_map, parameter_name):
    schema = {
        "type": "object",
        name_map: {parameter_name: {"type": "string", "description": "Pick\x07 one."}},
    }

    assert sanitize_input_schema(schema) == {
        "type": "object",
        name_map: {parameter_name: {"type": "string", "description": "Pick one."}},
    }


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"q\x07": {"type": "string"}}},
        {"type": "object", "$defs": {"Fil\x1bter": {"type": "object"}}},
        {"type": "object", "properties": {"q": {"type": "string", "descr\x1bption": "x"}}},
    ],
    ids=["parameter-name", "definition-name", "keyword"],
)
def test_a_key_with_a_control_character_is_refused(schema):
    with pytest.raises(UnsafeSchemaError, match="contains control characters"):
        sanitize_input_schema(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "enum": ["eu", "u\x07s"]},
        {"type": "string", "const": "e\x1bu"},
        {"type": "object", "const": {"region": "e\x1bu"}},
    ],
    ids=["enum", "const", "const-object"],
)
def test_an_enum_or_const_value_with_a_control_character_is_refused(schema):
    with pytest.raises(UnsafeSchemaError, match="enum or const value"):
        sanitize_input_schema({"type": "object", "properties": {"q": schema}})


def test_a_schema_nested_too_deeply_is_refused():
    schema: dict = {"type": "string"}
    for _ in range(2000):
        schema = {"type": "array", "items": schema}

    with pytest.raises(UnsafeSchemaError, match="nested too deeply"):
        sanitize_input_schema(schema)


def test_input_schema_is_not_mutated():
    schema = {"type": "object", "properties": {"q": {"type": "string", "description": "a\x07b"}}}
    original = copy.deepcopy(schema)

    sanitize_input_schema(schema)

    assert schema == original
