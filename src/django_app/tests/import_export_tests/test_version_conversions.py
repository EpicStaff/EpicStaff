"""
Tests for v1→v2 import/export version conversion and the shared variable_conversion helper.

These tests are pure dict-transform tests — no DB access required.
"""

import pytest

from src.shared.models import variable_adapter
from src.shared.models.variable_conversion import (
    _normalize_type,
    json_schema_node_to_nested_variable,
    args_schema_to_variables,
)
from tables.import_export.version_conversions.convertions import v1_to_v2


# ──────────────────────────────────────────
# _normalize_type
# ──────────────────────────────────────────


class TestNormalizeType:
    def test_integer_becomes_number(self):
        assert _normalize_type("integer") == "number"

    def test_none_becomes_string(self):
        assert _normalize_type(None) == "string"

    def test_empty_string_becomes_string(self):
        assert _normalize_type("") == "string"

    def test_passthrough_types(self):
        for t in ("string", "number", "boolean", "object", "array", "any"):
            assert _normalize_type(t) == t


# ──────────────────────────────────────────
# json_schema_node_to_nested_variable
# ──────────────────────────────────────────


class TestJsonSchemaNodeToNestedVariable:
    def test_primitive_string(self):
        node = {"type": "string", "description": "A name"}
        result = json_schema_node_to_nested_variable(node)
        assert result == {
            "type": "string",
            "description": "A name",
            "default_value": None,
        }

    def test_integer_normalized_to_number(self):
        node = {"type": "integer", "description": "A count", "default": 0}
        result = json_schema_node_to_nested_variable(node)
        assert result["type"] == "number"
        assert result["default_value"] == 0

    def test_nested_object_required_becomes_required_properties(self):
        node = {
            "type": "object",
            "properties": {
                "length": {"type": "number"},
                "width": {"type": "number"},
            },
            "required": ["length", "width"],
        }
        result = json_schema_node_to_nested_variable(node)
        assert result["type"] == "object"
        assert result["required_properties"] == ["length", "width"]
        assert "properties" in result
        assert result["properties"]["length"]["type"] == "number"
        assert result["properties"]["width"]["type"] == "number"
        assert "required" not in result
        assert "items" not in result

    def test_array_items_becomes_item(self):
        node = {
            "type": "array",
            "items": {"type": "string"},
        }
        result = json_schema_node_to_nested_variable(node)
        assert result["type"] == "array"
        assert result["item"] == {
            "type": "string",
            "description": "",
            "default_value": None,
        }
        assert "items" not in result

    def test_array_of_object_recursion(self):
        node = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["weight", "dimensions"],
                "properties": {
                    "make": {"type": "string"},
                    "model": {"type": "string"},
                    "weight": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Weight in kg.",
                    },
                    "dimensions": {
                        "type": "object",
                        "required": ["length", "width", "height"],
                        "properties": {
                            "width": {
                                "type": "number",
                                "minimum": 0,
                                "description": "Max width: 3.0m.",
                            },
                            "height": {
                                "type": "number",
                                "minimum": 0,
                                "description": "Max height: 3.85m.",
                            },
                            "length": {"type": "number", "minimum": 0},
                        },
                    },
                },
            },
            "minItems": 1,
        }
        result = json_schema_node_to_nested_variable(node)

        assert result["type"] == "array"
        item = result["item"]
        assert item["type"] == "object"
        assert set(item["required_properties"]) == {"weight", "dimensions"}

        dims = item["properties"]["dimensions"]
        assert dims["type"] == "object"
        assert set(dims["required_properties"]) == {"length", "width", "height"}
        assert dims["properties"]["width"]["type"] == "number"
        assert dims["properties"]["height"]["description"] == "Max height: 3.85m."

        assert item["properties"]["weight"]["description"] == "Weight in kg."
        assert item["properties"]["make"]["type"] == "string"

    def test_no_extra_keys_on_primitive(self):
        node = {"type": "boolean"}
        result = json_schema_node_to_nested_variable(node)
        assert set(result.keys()) == {"type", "description", "default_value"}


# ──────────────────────────────────────────
# v1_to_v2 converter — full bundle
# ──────────────────────────────────────────

_MACHINES_ARGS_SCHEMA = {
    "type": "object",
    "title": "ToolInputSchema",
    "required": ["machines"],
    "properties": {
        "machines": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["weight", "dimensions"],
                "properties": {
                    "make": {"type": "string"},
                    "model": {"type": "string"},
                    "weight": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Weight in kg. Max order capacity is 30,000kg.",
                    },
                    "dimensions": {
                        "type": "object",
                        "required": ["length", "width", "height"],
                        "properties": {
                            "width": {
                                "type": "number",
                                "minimum": 0,
                                "description": "Max width: 3.0m.",
                            },
                            "height": {
                                "type": "number",
                                "minimum": 0,
                                "description": "Max height: 3.85m.",
                            },
                            "length": {"type": "number", "minimum": 0},
                        },
                    },
                },
            },
            "minItems": 1,
        }
    },
}

_V1_BUNDLE = {
    "PythonCodeTool": [
        {
            "name": "FlatStringTool",
            "args_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
            },
            "python_code_tool_config_fields": [],
        },
        {
            "name": "IntegerArgTool",
            "args_schema": {
                "type": "object",
                "required": ["count"],
                "properties": {
                    "count": {"type": "integer", "description": "How many"},
                },
            },
            "python_code_tool_config_fields": [],
        },
        {
            "name": "SplitMachinesIntoOrders",
            "args_schema": _MACHINES_ARGS_SCHEMA,
            "python_code_tool_config_fields": [],
        },
        {
            "name": "ToolWithConfigField",
            "args_schema": {
                "type": "object",
                "required": [],
                "properties": {},
            },
            "python_code_tool_config_fields": [
                {
                    "name": "api_key",
                    "data_type": "string",
                    "description": "The API key",
                    "required": True,
                }
            ],
        },
    ]
}


class TestV1ToV2:
    def _convert(self):
        import copy

        return v1_to_v2(copy.deepcopy(_V1_BUNDLE))

    def test_args_schema_removed(self):
        result = self._convert()
        for tool in result["PythonCodeTool"]:
            assert "args_schema" not in tool

    def test_python_code_tool_config_fields_removed(self):
        result = self._convert()
        for tool in result["PythonCodeTool"]:
            assert "python_code_tool_config_fields" not in tool

    def test_flat_string_variable_validates(self):
        result = self._convert()
        tool = next(
            t for t in result["PythonCodeTool"] if t["name"] == "FlatStringTool"
        )
        assert len(tool["variables"]) == 1
        variable_adapter.validate_python(tool["variables"][0])

    def test_integer_arg_normalizes_to_number_and_validates(self):
        result = self._convert()
        tool = next(
            t for t in result["PythonCodeTool"] if t["name"] == "IntegerArgTool"
        )
        var = tool["variables"][0]
        assert var["type"] == "number"
        variable_adapter.validate_python(var)

    def test_machines_array_of_object_validates(self):
        result = self._convert()
        tool = next(
            t
            for t in result["PythonCodeTool"]
            if t["name"] == "SplitMachinesIntoOrders"
        )
        assert len(tool["variables"]) == 1
        var = tool["variables"][0]
        assert var["name"] == "machines"
        assert var["type"] == "array"
        assert var["required"] is True
        assert var["input_type"] == "agent_input"
        # must not raise
        variable_adapter.validate_python(var)

    def test_config_field_user_input_validates(self):
        result = self._convert()
        tool = next(
            t for t in result["PythonCodeTool"] if t["name"] == "ToolWithConfigField"
        )
        assert len(tool["variables"]) == 1
        var = tool["variables"][0]
        assert var["input_type"] == "user_input"
        assert var["name"] == "api_key"
        variable_adapter.validate_python(var)

    def test_all_variables_in_all_tools_validate(self):
        result = self._convert()
        for tool in result["PythonCodeTool"]:
            for var in tool["variables"]:
                variable_adapter.validate_python(var)

    def test_bundle_without_python_code_tool_key_passes_through(self):
        data = {"Flow": [{"id": 1}]}
        result = v1_to_v2(data)
        assert result == {"Flow": [{"id": 1}]}
