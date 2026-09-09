"""
Tests for v1→v2 and v2→v3 import/export version conversion, and the shared
variable_conversion helper.

These tests are pure dict-transform tests — no DB access required.
"""

import copy

import pytest

from src.shared.models import variable_adapter
from src.shared.models.variable_conversion import (
    _normalize_type,
    json_schema_node_to_nested_variable,
    args_schema_to_variables,
)
from tables.import_export.version_conversions.convertions import v1_to_v2, v2_to_v3


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

    def test_list_type_nullable_integer_becomes_number(self):
        assert _normalize_type(["integer", "null"]) == "number"

    def test_list_type_null_only_becomes_string(self):
        assert _normalize_type(["null"]) == "string"

    def test_list_type_string_nullable_becomes_string(self):
        assert _normalize_type(["string", "null"]) == "string"


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

    def test_list_type_nullable_integer_no_crash(self):
        node = {"type": ["integer", "null"], "default": None, "description": "x"}
        result = json_schema_node_to_nested_variable(node)
        assert result["type"] == "number"


# ──────────────────────────────────────────
# args_schema_to_variables — per-property input_type
# ──────────────────────────────────────────


class TestArgsSchemaToVariablesInputType:
    def test_property_input_type_overrides_default(self):
        args_schema = {
            "type": "object",
            "required": ["api_key"],
            "properties": {
                "api_key": {"type": "string", "input_type": "user_input"},
            },
        }
        variables = args_schema_to_variables(args_schema, input_type="agent_input")
        assert variables[0]["input_type"] == "user_input"

    def test_invalid_property_input_type_raises_value_error(self):
        args_schema = {
            "type": "object",
            "required": ["api_key"],
            "properties": {
                "api_key": {"type": "string", "input_type": "user_inpt"},
            },
        }
        with pytest.raises(ValueError, match="api_key"):
            args_schema_to_variables(args_schema)


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


# ──────────────────────────────────────────
# v2_to_v3 converter — full bundle
# ──────────────────────────────────────────


class TestV2ToV3:
    def _convert(self, bundle):
        return v2_to_v3(copy.deepcopy(bundle))

    def test_crew_node_left_untouched(self):
        bundle = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {
                            "id": 100,
                            "node_type": "CrewNode",
                            "graph": 10,
                            "node_name": "Crew Node #1",
                            "input_map": {"topic": "static:AI"},
                            "output_variable_path": "result",
                            "metadata": {"nodeNumber": 1},
                            "crew": 200,
                        }
                    ],
                }
            ]
        }
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        assert result["Flow"][0]["nodes"][0] == original_node

    def test_code_agent_node_left_untouched(self):
        bundle = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {
                            "id": 999,
                            "node_type": "CodeAgentNode",
                            "graph": 10,
                            "some_legacy_field": "unchanged",
                        }
                    ],
                }
            ]
        }
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        assert result["Flow"][0]["nodes"][0] == original_node

    def test_python_node_stream_config_removed(self):
        bundle = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {
                            "id": 500,
                            "node_type": "PythonNode",
                            "graph": 10,
                            "node_name": "Python Node #1",
                            "stream_config": {"enabled": True},
                            "python_code": {"code": "print(1)"},
                        }
                    ],
                }
            ]
        }

        result = self._convert(bundle)
        node = result["Flow"][0]["nodes"][0]

        assert "stream_config" not in node
        assert node["node_name"] == "Python Node #1"
        assert node["python_code"] == {"code": "print(1)"}

    def test_classification_decision_table_prompt_id_remapped(self):
        bundle = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {
                            "id": 600,
                            "node_type": "ClassificationDecisionTableNode",
                            "graph": 10,
                            "prompt_configs": [
                                {"id": 50, "prompt_key": "intent_a"},
                                {"id": 51, "prompt_key": "intent_b"},
                            ],
                            "condition_groups": [
                                {"id": 700, "prompt_id": "intent_b"},
                                {"id": 701, "prompt_id": "unknown_key"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = self._convert(bundle)
        node = result["Flow"][0]["nodes"][0]
        groups = {group["id"]: group for group in node["condition_groups"]}

        assert groups[700]["prompt"] == 51
        assert "prompt_id" not in groups[700]
        assert groups[701]["prompt"] is None
        assert "prompt_id" not in groups[701]

    def test_classification_decision_table_prompt_id_remapped_legacy_shape(self):
        # Genuine 1.1.2-era prompt_configs carry no "id" — only prompt_key.
        bundle = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {
                            "id": 601,
                            "node_type": "ClassificationDecisionTableNode",
                            "graph": 10,
                            "prompt_configs": [
                                {"prompt_key": "intent_a"},
                                {"prompt_key": "intent_b"},
                            ],
                            "condition_groups": [
                                {"id": 800, "prompt_id": "intent_b"},
                            ],
                        }
                    ],
                }
            ]
        }

        result = self._convert(bundle)
        node = result["Flow"][0]["nodes"][0]
        group = node["condition_groups"][0]

        assert group["prompt"] == "intent_b"
        assert group["prompt"] is not None
        assert "prompt_id" not in group

    def test_bundle_without_relevant_node_types_passes_through(self):
        data = {
            "Flow": [
                {
                    "id": 10,
                    "nodes": [
                        {"id": 1, "node_type": "StartNode", "graph": 10},
                    ],
                }
            ]
        }
        expected = copy.deepcopy(data)

        result = v2_to_v3(data)

        assert result == expected

    def test_bundle_without_flow_key_passes_through(self):
        data = {"Agent": [{"id": 1}]}
        result = v2_to_v3(data)
        assert result == {"Agent": [{"id": 1}]}

    def test_stale_llm_config_field_stripped(self):
        data = {
            "LLMConfig": [
                {
                    "id": 400,
                    "custom_name": "My LLM Config",
                    "temperature": 0.7,
                    "response_format": None,
                }
            ]
        }

        result = v2_to_v3(data)
        llm_config = result["LLMConfig"][0]

        assert "response_format" not in llm_config
        assert llm_config["custom_name"] == "My LLM Config"
        assert llm_config["temperature"] == 0.7
        assert llm_config["id"] == 400

    def test_llm_config_with_only_valid_fields_passes_through_unchanged(self):
        data = {
            "LLMConfig": [
                {
                    "id": 401,
                    "custom_name": "Another Config",
                    "temperature": 0.5,
                    "max_tokens": 4096,
                    "tags": [1, 2],
                }
            ]
        }
        expected = copy.deepcopy(data)

        result = v2_to_v3(data)

        # tags is M2M (no DB column) — must survive a naive "f.concrete" check.
        assert result == expected

    def test_stale_embedding_config_field_stripped(self):
        data = {
            "EmbeddingConfig": [
                {
                    "id": 500,
                    "custom_name": "My Embedding Config",
                    "task_type": "retrieval_document",
                    "dimensions": 1536,
                }
            ]
        }

        result = v2_to_v3(data)
        embedding_config = result["EmbeddingConfig"][0]

        assert "dimensions" not in embedding_config
        assert embedding_config["custom_name"] == "My Embedding Config"
        assert embedding_config["task_type"] == "retrieval_document"
        assert embedding_config["id"] == 500

    def test_stale_mcp_tool_field_stripped(self):
        data = {
            "MCPTool": [
                {
                    "id": 600,
                    "name": "My MCP Tool",
                    "transport": "https://example.com/mcp",
                    "tool_name": "search",
                    "timeout": 30,
                    "init_timeout": 10,
                    "labels": [1, 2],
                    "auth": "legacy-token",
                }
            ]
        }

        result = v2_to_v3(data)
        mcp_tool = result["MCPTool"][0]

        assert "auth" not in mcp_tool
        assert mcp_tool["name"] == "My MCP Tool"
        assert mcp_tool["transport"] == "https://example.com/mcp"
        assert mcp_tool["tool_name"] == "search"
        assert mcp_tool["timeout"] == 30
        assert mcp_tool["init_timeout"] == 10
        assert mcp_tool["labels"] == [1, 2]
        assert mcp_tool["id"] == 600

    def test_stale_python_code_tool_field_stripped(self):
        # "favorite" was a boolean field on PythonCodeTool, removed in
        # migration 0209 in favor of a separate PythonCodeToolFavorite
        # model. Pre-0209 (1.1.2-era) exports still carry it as a top-level
        # key, which would otherwise crash find_existing()'s create_filters()
        # with FieldError.
        data = {
            "PythonCodeTool": [
                {
                    "id": 700,
                    "name": "CLI Executor Tool",
                    "description": "Runs a shell command",
                    "python_code": {
                        "libraries": "",
                        "code": "print('hi')",
                        "entrypoint": "main",
                        "global_kwargs": {},
                    },
                    "python_code_tool_config": [],
                    "variables": [
                        {
                            "name": "command",
                            "type": "string",
                            "required": True,
                            "input_type": "agent_input",
                            "description": "Command to run",
                            "default_value": None,
                        }
                    ],
                    "built_in": True,
                    "use_storage": False,
                    "labels": [1, 2],
                    "favorite": True,
                }
            ]
        }

        result = v2_to_v3(data)
        python_code_tool = result["PythonCodeTool"][0]

        assert "favorite" not in python_code_tool
        assert python_code_tool["id"] == 700
        assert python_code_tool["name"] == "CLI Executor Tool"
        assert python_code_tool["description"] == "Runs a shell command"
        assert python_code_tool["built_in"] is True
        assert python_code_tool["use_storage"] is False
        assert python_code_tool["labels"] == [1, 2]
        assert python_code_tool["variables"] == data["PythonCodeTool"][0]["variables"]
        # These are handled specially by find_existing()/create_entity() and
        # must survive the generic stale-field strip untouched.
        assert python_code_tool["python_code"] == {
            "libraries": "",
            "code": "print('hi')",
            "entrypoint": "main",
            "global_kwargs": {},
        }
        assert python_code_tool["python_code_tool_config"] == []

    def test_python_code_tool_with_only_valid_fields_passes_through_unchanged(self):
        data = {
            "PythonCodeTool": [
                {
                    "id": 701,
                    "name": "Well-formed Tool",
                    "description": "Already current-shape",
                    "python_code": {
                        "libraries": "requests",
                        "code": "print('ok')",
                        "entrypoint": "main",
                        "global_kwargs": {},
                    },
                    "python_code_tool_config": [
                        {"name": "api_key", "configuration": {"secret_id": 9}}
                    ],
                    "variables": [],
                    "built_in": False,
                    "use_storage": True,
                    "labels": [],
                }
            ]
        }
        expected = copy.deepcopy(data)

        result = v2_to_v3(data)

        assert result == expected
