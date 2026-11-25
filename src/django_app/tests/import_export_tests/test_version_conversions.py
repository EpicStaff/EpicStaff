"""
Tests for v1→v2, v2→v3, v3→v4, v4→v5 and v5→v6 import/export version conversion,
and the shared variable_conversion helper.

These tests are pure dict-transform tests — no DB access required.
"""

import copy
import time

import pytest

from src.shared.models import variable_adapter
from src.shared.models.variable_conversion import (
    json_schema_node_to_nested_variable,
    args_schema_to_variables,
)
from tables.import_export.constants import IMPORT_VERSION
from tables.import_export.enums import EntityType
from tables.import_export.constants import VENV_NAME_MAX_LENGTH
from tables.import_export.serializers.venv import VenvImportSerializer
from tables.import_export.version_conversions.base import VersionConverter
from tables.import_export.version_conversions.convertions import (
    v1_to_v2,
    v2_to_v3,
    v3_to_v4,
    v4_to_v5,
    v5_to_v6,
)
from tables.utils.legacy_node_number import split_legacy_node_name


# ──────────────────────────────────────────
# JSON Schema type -> variable type
# ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("schema_type", "variable_type"),
    [
        ("integer", "number"),
        (None, "string"),
        ("", "string"),
        *[(kept, kept) for kept in ("string", "number", "boolean", "object", "array", "any")],
        (["integer", "null"], "number"),
        (["null"], "string"),
        (["string", "null"], "string"),
    ],
)
def test_json_schema_types_map_to_variable_types(schema_type, variable_type):
    assert json_schema_node_to_nested_variable({"type": schema_type})["type"] == variable_type


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

    def test_legacy_llm_config_headers_merged_into_extra_headers(self):
        data = {
            "LLMConfig": [
                {
                    "id": 402,
                    "custom_name": "Merged Config",
                    "headers": {"X-Legacy": "legacy-value", "X-Shared": "from-legacy"},
                    "extra_headers": {"X-New": "new-value", "X-Shared": "from-extra"},
                }
            ]
        }

        result = v2_to_v3(data)
        llm_config = result["LLMConfig"][0]

        assert "headers" not in llm_config
        assert llm_config["extra_headers"] == {
            "X-Legacy": "legacy-value",
            "X-New": "new-value",
            "X-Shared": "from-extra",
        }

    def test_llm_config_without_headers_passes_through_unaffected(self):
        data = {
            "LLMConfig": [
                {
                    "id": 403,
                    "custom_name": "No Legacy Headers",
                    "extra_headers": {"X-New": "new-value"},
                }
            ]
        }
        expected = copy.deepcopy(data)

        result = v2_to_v3(data)

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


# ──────────────────────────────────────────
# v3_to_v4 converter — badge number moves into node_number
# ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("node_name", "metadata_number", "expected"),
    [
        ("Python-Node #3", 3, ("Python-Node", 3)),
        ("Step #2", 5, ("Step #2", 5)),
        ("Agent #4", None, ("Agent", 4)),
        ("Plain", None, ("Plain", None)),
        ("Plain", 6, ("Plain", 6)),
        ("#7", None, ("#7", 7)),
        ("Agent # 4 ", 4, ("Agent", 4)),
        ("Agent #4", True, ("Agent", 4)),
        ("Agent #4", "4", ("Agent", 4)),
        ("Agent #4", 0, ("Agent", 4)),
        ("Agent #1000000", None, ("Agent", 1_000_000)),
        ("Agent #1000001", None, ("Agent #1000001", None)),
        ("Plain", 1_000_001, ("Plain", None)),
        ("Order #20240101123456", None, ("Order #20240101123456", None)),
        ("Order #20240101123456", 3, ("Order #20240101123456", 3)),
        ("", None, ("", None)),
        (None, None, (None, None)),
        (None, 4, (None, 4)),
        ("  Agent  #  4  ", None, ("  Agent", 4)),
        ("Agent\n#4\n", None, ("Agent", 4)),
        ("Agent\u00a0#\u30004", None, ("Agent", 4)),
        ("Agent #\u0663", None, ("Agent", 3)),
        ("Agent #\u00b2", None, ("Agent #\u00b2", None)),
        ("A #1 #2", None, ("A #1", 2)),
        ("A #2 x", None, ("A #2 x", None)),
        ("Agent #", None, ("Agent #", None)),
        ("Agent 4", None, ("Agent 4", None)),
        ("42", None, ("42", None)),
        ("   #4", None, ("   #4", 4)),
    ],
)
def test_split_legacy_node_name(node_name, metadata_number, expected):
    assert split_legacy_node_name(node_name, metadata_number) == expected


@pytest.mark.parametrize(
    "node_name",
    [
        pytest.param("a" + " " * 20_000 + "b", id="no-hash"),
        pytest.param("a" + " " * 20_000 + "#x", id="hash-no-digits"),
    ],
)
def test_split_legacy_node_name_runs_in_linear_time_on_long_inner_whitespace(node_name):
    # Sized so the former quadratic regex search took about a second per case.
    started = time.perf_counter()

    result = split_legacy_node_name(node_name, None)

    assert time.perf_counter() - started < 0.1
    assert result == (node_name, None)


def _v3_bundle(*nodes):
    return {"version": 3, "main_entity": "Flow", "Flow": [{"id": 10, "nodes": list(nodes)}]}


class TestV3ToV4:
    def test_badge_moves_from_name_and_metadata_into_node_number(self):
        bundle = _v3_bundle(
            {
                "id": 1,
                "node_type": "AgentNode",
                "node_name": "Agent #4",
                "metadata": {"nodeNumber": 4, "position": {"x": 1, "y": 2}},
            }
        )

        node = v3_to_v4(bundle)["Flow"][0]["nodes"][0]

        assert node["node_name"] == "Agent"
        assert node["node_number"] == 4
        assert node["metadata"] == {"position": {"x": 1, "y": 2}}

    def test_name_suffix_that_is_not_the_badge_is_kept(self):
        bundle = _v3_bundle(
            {"id": 1, "node_type": "PythonNode", "node_name": "Step #2", "metadata": {"nodeNumber": 5}}
        )

        node = v3_to_v4(bundle)["Flow"][0]["nodes"][0]

        assert (node["node_name"], node["node_number"], node["metadata"]) == ("Step #2", 5, {})

    def test_node_that_already_has_node_number_is_left_untouched(self):
        # Snapshots rewritten by the backfill migration are clean but still say version 3.
        node = {"id": 1, "node_type": "PythonNode", "node_name": "Step #2", "node_number": 5}
        bundle = _v3_bundle(copy.deepcopy(node))

        assert v3_to_v4(bundle)["Flow"][0]["nodes"][0] == node

    def test_node_without_a_name_is_left_untouched(self):
        node = {"id": 2, "node_type": "StartNode", "metadata": {"nodeNumber": 1}}
        bundle = _v3_bundle(copy.deepcopy(node))

        assert v3_to_v4(bundle)["Flow"][0]["nodes"][0] == node

    def test_bundle_without_flow_key_passes_through(self):
        bundle = {"version": 3, "LLMConfig": [{"id": 1}]}

        assert v3_to_v4(copy.deepcopy(bundle)) == bundle

    def test_version_converter_brings_a_v3_file_to_the_current_version(self):
        bundle = _v3_bundle({"id": 1, "node_type": "AgentNode", "node_name": "Agent #4"})

        converted = VersionConverter.convert(bundle)

        assert converted["version"] == IMPORT_VERSION
        node = converted["Flow"][0]["nodes"][0]
        assert (node["node_name"], node["node_number"]) == ("Agent", 4)

def _tool(name: str, libraries: str) -> dict:
    return {"name": name, "python_code": {"code": f"# {name}", "libraries": libraries}}


def _flow(*nodes: dict) -> dict:
    return {"nodes": list(nodes)}


class TestV4ToV5:
    """Libraries move off the code and onto an environment of their own.

    A v4 file declares them as a space-separated string per code slot; v5 carries a
    `Venv` entry and the code only names which one it runs in.
    """

    def test_libraries_become_an_environment_the_code_names(self):
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("scraper", "httpx>=0.28")]})

        [venv] = data[EntityType.VENV]
        assert venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]
        assert data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]["venv"] == venv["id"]
        assert "libraries" not in data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]

    def test_the_same_libraries_share_one_environment(self):
        """In v3 they were one install; keeping them apart would build it twice."""
        data = v4_to_v5(
            {
                EntityType.PYTHON_CODE_TOOL: [
                    _tool("one", "httpx beautifulsoup4"),
                    _tool("two", "beautifulsoup4 httpx"),
                ]
            }
        )

        assert len(data[EntityType.VENV]) == 1
        tools = data[EntityType.PYTHON_CODE_TOOL]
        assert tools[0]["python_code"]["venv"] == tools[1]["python_code"]["venv"]

    def test_different_libraries_get_their_own(self):
        data = v4_to_v5(
            {EntityType.PYTHON_CODE_TOOL: [_tool("one", "httpx"), _tool("two", "pydantic")]}
        )

        assert len(data[EntityType.VENV]) == 2

    def test_code_without_libraries_names_no_environment(self):
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("plain", "")]})

        assert EntityType.VENV not in data
        assert "venv" not in data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]

    def test_every_code_slot_of_a_flow_is_converted(self):
        data = v4_to_v5(
            {
                EntityType.GRAPH: [
                    _flow(
                        {
                            "node_type": "PythonNode",
                            "node_name": "n1",
                            "python_code": {"code": "a", "libraries": "httpx"},
                        },
                        {
                            "node_type": "WebhookTriggerNode",
                            "node_name": "n2",
                            "python_code": {"code": "b", "libraries": "httpx"},
                        },
                        {
                            "node_type": "ClassificationDecisionTableNode",
                            "node_name": "n3",
                            "pre_python_code": {"code": "c", "libraries": "httpx"},
                            "post_python_code": {"code": "d", "libraries": "pydantic"},
                        },
                        {"node_type": "StartNode", "node_name": "n4"},
                    )
                ]
            }
        )

        nodes = {node["node_name"]: node for node in data[EntityType.GRAPH][0]["nodes"]}
        shared = nodes["n1"]["python_code"]["venv"]
        assert nodes["n2"]["python_code"]["venv"] == shared
        assert nodes["n3"]["pre_python_code"]["venv"] == shared
        assert nodes["n3"]["post_python_code"]["venv"] != shared

    def test_an_environment_is_named_after_what_first_asked_for_it(self):
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("scraper", "httpx")]})

        assert data[EntityType.VENV][0]["name"] == "scraper-venv"

    @pytest.mark.parametrize(
        ("owner", "expected"),
        [
            ("File Compressor Tool #2", "File Compressor Tool 2-venv"),
            ("fetch (v1.2): main", "fetch v1 2 main-venv"),
            ("Інструмент", "imported-venv-1"),
            ("#!", "imported-venv-1"),
        ],
    )
    def test_a_name_the_sandbox_would_refuse_is_reduced_to_the_characters_it_takes(
        self, owner, expected
    ):
        """Tool and node names may hold any character, a venv name may not; copies made
        by v1.3 are even named with a `#`, so a legacy file carries them routinely."""
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool(owner, "httpx")]})

        assert data[EntityType.VENV][0]["name"] == expected

    def test_a_long_owner_name_still_fits_the_sandbox(self):
        data = v4_to_v5(
            {
                EntityType.PYTHON_CODE_TOOL: [
                    _tool("x" * 400, "httpx"),
                    _tool("x" * 400 + " copy", "pydantic"),
                ]
            }
        )

        names = [venv["name"] for venv in data[EntityType.VENV]]
        assert all(len(name) <= VENV_NAME_MAX_LENGTH for name in names)
        assert len(set(names)) == 2

    def test_a_cut_owner_name_leaves_no_space_before_the_suffix(self):
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("a" * 249 + " b", "httpx")]})

        assert data[EntityType.VENV][0]["name"] == "a" * 249 + "-venv"

    def test_an_entry_pip_cannot_read_is_dropped_and_the_rest_kept(self):
        """A legacy file cannot be edited to fix it, and a flow that arrives without
        one library is worth more than one that does not arrive."""
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("x", "httpx ../../etc/passwd")]})

        assert data[EntityType.VENV][0]["libs"] == [{"name": "httpx", "specification": ""}]

    def test_extras_are_dropped(self):
        """A venv library is a name and a specifier; there is nowhere to put extras."""
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool("x", "requests[socks]>=2")]})

        assert data[EntityType.VENV][0]["libs"] == [{"name": "requests", "specification": ">=2"}]

    @pytest.mark.parametrize(
        "libraries",
        ["httpx>=0.28", "requests[socks]>=2", "httpx ../../etc/passwd", "pydantic==2.0,<3"],
    )
    @pytest.mark.parametrize("owner", ["x", "Tool #2", "Інструмент", "y" * 400])
    def test_what_it_produces_has_the_shape_the_importer_reads(self, libraries, owner):
        """The converter feeds the venv serializer, so its output has to pass it.
        Whether the values build is the sandbox's call, not checked here."""
        data = v4_to_v5({EntityType.PYTHON_CODE_TOOL: [_tool(owner, libraries)]})

        for venv in data.get(EntityType.VENV, []):
            serializer = VenvImportSerializer(data=venv)
            assert serializer.is_valid(), serializer.errors


GATEWAY = "https://gateway.example/openai"


def _v5_llm_model(**fields) -> dict:
    return {"id": 7, "name": "gateway-gpt", "provider_name": "azure", "is_custom": True, **fields}


def _v5_llm_config(**fields) -> dict:
    return {"id": 70, "custom_name": "gateway config", "model": 7, **fields}


class TestV5ToV6:
    """Setting columns fold into `parameters`, endpoint columns into `connection`.

    The same fold the database migration did: only non-null settings, only non-empty
    endpoints, and a model row's endpoint only when the row is the organization's own.
    """

    def test_llm_setting_columns_become_parameters(self):
        data = v5_to_v6(
            {
                EntityType.LLM_CONFIG: [
                    _v5_llm_config(temperature=0.3, max_tokens=1000, top_p=None, stop=["END"])
                ]
            }
        )

        [config] = data[EntityType.LLM_CONFIG]
        assert config["parameters"] == {"temperature": 0.3, "max_tokens": 1000, "stop": ["END"]}
        assert "temperature" not in config and "top_p" not in config

    def test_a_custom_model_s_endpoint_moves_onto_the_config(self):
        data = v5_to_v6(
            {
                EntityType.LLM_MODEL: [
                    _v5_llm_model(base_url=GATEWAY, api_version="2024-06-01", deployment_id="prod")
                ],
                EntityType.LLM_CONFIG: [_v5_llm_config(base_url=None, api_version=None)],
            }
        )

        assert data[EntityType.LLM_CONFIG][0]["connection"] == {
            "base_url": GATEWAY,
            "api_version": "2024-06-01",
            "deployment_id": "prod",
        }
        model = data[EntityType.LLM_MODEL][0]
        assert not {"base_url", "api_version", "deployment_id"} & model.keys()

    def test_the_model_s_endpoint_wins_over_the_config_s_own(self):
        # Runs read the endpoint from the model row only; the config's fills what the row lacks.
        data = v5_to_v6(
            {
                EntityType.LLM_MODEL: [_v5_llm_model(base_url=GATEWAY, api_version="")],
                EntityType.LLM_CONFIG: [
                    _v5_llm_config(base_url="https://own.example", api_version="2024-06-01")
                ],
            }
        )

        assert data[EntityType.LLM_CONFIG][0]["connection"] == {
            "base_url": GATEWAY,
            "api_version": "2024-06-01",
        }

    def test_a_built_in_model_s_endpoint_is_not_copied(self):
        data = v5_to_v6(
            {
                EntityType.LLM_MODEL: [_v5_llm_model(is_custom=False, base_url=GATEWAY)],
                EntityType.LLM_CONFIG: [_v5_llm_config()],
            }
        )

        assert data[EntityType.LLM_CONFIG][0]["connection"] == {}
        assert "base_url" not in data[EntityType.LLM_MODEL][0]

    def test_embedding_task_type_and_model_endpoint_are_folded(self):
        data = v5_to_v6(
            {
                EntityType.EMBEDDING_MODEL: [
                    {"id": 3, "name": "embedder", "is_custom": True, "base_url": GATEWAY, "deployment": "emb"}
                ],
                EntityType.EMBEDDING_CONFIG: [
                    {"id": 30, "custom_name": "embed", "model": 3, "task_type": "retrieval_document"}
                ],
            }
        )

        [config] = data[EntityType.EMBEDDING_CONFIG]
        assert config["parameters"] == {"task_type": "retrieval_document"}
        assert config["connection"] == {"base_url": GATEWAY, "deployment_id": "emb"}
        assert "task_type" not in config
        assert not {"base_url", "deployment"} & data[EntityType.EMBEDDING_MODEL][0].keys()

    def test_a_config_whose_model_is_not_in_the_file_gets_only_its_own_values(self):
        data = v5_to_v6({EntityType.LLM_CONFIG: [_v5_llm_config(model=999, base_url=GATEWAY)]})

        assert data[EntityType.LLM_CONFIG][0]["connection"] == {"base_url": GATEWAY}

    def test_a_file_without_configs_passes_through(self):
        bundle = {"version": 5, EntityType.GRAPH: [{"id": 1, "nodes": []}]}

        assert v5_to_v6(copy.deepcopy(bundle)) == bundle

    def test_a_version_1_file_reaches_the_current_version_with_its_settings(self):
        """v2->v3 strips fields the current model lacks; the folded columns must survive it."""
        bundle = {
            EntityType.LLM_MODEL: [_v5_llm_model(base_url=GATEWAY)],
            EntityType.LLM_CONFIG: [
                _v5_llm_config(temperature=0.2, base_url=None, headers={"X-Legacy": "1"})
            ],
            EntityType.EMBEDDING_CONFIG: [
                {"id": 30, "custom_name": "embed", "model": 3, "task_type": "retrieval_query"}
            ],
        }

        converted = VersionConverter.convert(bundle)

        assert converted["version"] == IMPORT_VERSION == 6
        [config] = converted[EntityType.LLM_CONFIG]
        assert config["parameters"] == {"temperature": 0.2}
        assert config["connection"] == {"base_url": GATEWAY}
        assert config["extra_headers"] == {"X-Legacy": "1"}
        assert converted[EntityType.EMBEDDING_CONFIG][0]["parameters"] == {
            "task_type": "retrieval_query"
        }


# ──────────────────────────────────────────
# Node files (partial exports) and entries already in a newer shape
# ──────────────────────────────────────────


class TestNodeFileConversion:
    """A node file lists its nodes at the top level, untagged, and may carry no version.

    Without a version it runs through every conversion, so each one converts the nodes
    of a node file as it does a flow's, and leaves what is already newer as it is.
    """

    def test_python_node_stream_config_is_removed_from_a_node_file(self):
        data = v2_to_v3({EntityType.PYTHON_NODE: [{"id": 1, "stream_config": {"enabled": True}}]})

        assert data[EntityType.PYTHON_NODE] == [{"id": 1}]

    def test_classification_prompt_id_is_remapped_in_a_node_file(self):
        data = v2_to_v3(
            {
                EntityType.CLASSIFICATION_DECISION_TABLE_NODE: [
                    {
                        "id": 1,
                        "prompt_configs": [{"prompt_key": "triage", "prompt_text": "..."}],
                        "condition_groups": [{"group_name": "a", "prompt_id": "triage"}],
                    }
                ]
            }
        )

        [node] = data[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
        assert node["condition_groups"] == [{"group_name": "a", "prompt": "triage"}]

    def test_badge_moves_into_node_number_in_a_node_file(self):
        data = v3_to_v4(
            {EntityType.AGENT_NODE: [{"id": 1, "node_name": "Agent #4", "metadata": {"nodeNumber": 4}}]}
        )

        assert data[EntityType.AGENT_NODE] == [
            {"id": 1, "node_name": "Agent", "node_number": 4, "metadata": {}}
        ]

    def test_libraries_of_a_node_file_become_an_environment(self):
        data = v4_to_v5(
            {
                EntityType.PYTHON_NODE: [
                    {
                        "id": 1,
                        "node_name": "fetch",
                        "python_code": {"code": "...", "libraries": "httpx>=0.28"},
                    }
                ],
                EntityType.CLASSIFICATION_DECISION_TABLE_NODE: [
                    {
                        "id": 2,
                        "node_name": "route",
                        "pre_python_code": {"code": "...", "libraries": "httpx>=0.28"},
                        "post_python_code": {"code": "...", "libraries": ""},
                    }
                ],
            }
        )

        [venv] = data[EntityType.VENV]
        assert venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]
        [python_node] = data[EntityType.PYTHON_NODE]
        [table] = data[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
        assert python_node["python_code"] == {"code": "...", "venv": venv["id"]}
        assert table["pre_python_code"] == {"code": "...", "venv": venv["id"]}
        assert table["post_python_code"] == {"code": "..."}

    def test_an_unversioned_release_1_3_node_file_reaches_the_current_shape(self):
        node_file = {
            EntityType.PYTHON_NODE: [
                {
                    "id": 1,
                    "node_name": "Fetch #2",
                    "metadata": {"nodeNumber": 2},
                    "python_code": {"code": "...", "libraries": "httpx"},
                }
            ],
            EntityType.PYTHON_CODE_TOOL: [
                {
                    "id": 5,
                    "name": "lookup",
                    "args_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                    "python_code_tool_config_fields": [],
                    "python_code": {"code": "...", "libraries": ""},
                }
            ],
        }

        converted = VersionConverter.convert(node_file)

        assert converted["version"] == IMPORT_VERSION
        [python_node] = converted[EntityType.PYTHON_NODE]
        assert (python_node["node_name"], python_node["node_number"]) == ("Fetch", 2)
        [venv] = converted[EntityType.VENV]
        assert python_node["python_code"]["venv"] == venv["id"]
        [tool] = converted[EntityType.PYTHON_CODE_TOOL]
        assert [variable["name"] for variable in tool["variables"]] == ["q"]
        assert "args_schema" not in tool

    def test_a_tool_already_in_the_v2_shape_keeps_its_variables(self):
        variables = [{"name": "q", "type": "string", "input_type": "agent_input"}]
        tool = {"id": 5, "name": "lookup", "variables": variables}

        data = v1_to_v2({EntityType.PYTHON_CODE_TOOL: [copy.deepcopy(tool)]})

        assert data[EntityType.PYTHON_CODE_TOOL] == [tool]

    def test_code_already_naming_an_environment_is_left_as_it_is(self):
        node_file = {
            EntityType.VENV: [{"id": 3, "name": "fetch-venv", "libs": []}],
            EntityType.PYTHON_NODE: [{"id": 1, "python_code": {"code": "...", "venv": 3}}],
        }

        assert v4_to_v5(copy.deepcopy(node_file)) == node_file

    def test_a_config_already_in_the_v6_shape_keeps_its_parameters_and_connection(self):
        node_file = {
            EntityType.LLM_MODEL: [_v5_llm_model()],
            EntityType.LLM_CONFIG: [
                _v5_llm_config(
                    parameters={"temperature": 0.7}, connection={"base_url": GATEWAY}
                )
            ],
            EntityType.EMBEDDING_CONFIG: [
                {
                    "id": 30,
                    "model": 3,
                    "parameters": {"task_type": "retrieval_query"},
                    "connection": {},
                }
            ],
        }

        assert v5_to_v6(copy.deepcopy(node_file)) == node_file
