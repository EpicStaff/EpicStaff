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


def _trivial_crew_bundle():
    return {
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
        ],
        "Project": [
            {
                "id": 200,
                "name": "Research Crew",
                "process": "sequential",
                "manager_llm_config": None,
                "planning": False,
                "planning_llm_config": None,
                "memory": False,
                "memory_llm_config": None,
                "embedding_config": None,
                "tasks": [
                    {
                        "id": 1,
                        "name": "Research task",
                        "agent": 300,
                        "instructions": "Research the topic",
                        "expected_output": "A research summary",
                        "order": 1,
                        "context": [],
                        "knowledge_query": "some query",
                        "human_input": True,
                        "async_execution": False,
                        "config": {"foo": "bar"},
                    },
                    {
                        "id": 2,
                        "name": "Write task",
                        "agent": 300,
                        "instructions": "Write the report",
                        "expected_output": None,
                        "order": 2,
                        "context": [1],
                        "knowledge_query": None,
                        "human_input": False,
                        "async_execution": False,
                        "config": None,
                    },
                ],
            }
        ],
        "Agent": [
            {
                "id": 300,
                "role": "Senior Researcher",
                "goal": "Find accurate information",
                "backstory": "Years of experience in research",
                "llm_config": 5,
                "fcm_llm_config": None,
                "max_iter": 15,
                "max_rpm": 50,
                "max_execution_time": None,
                "cache": True,
                "max_retry_limit": 3,
                "default_temperature": 0.5,
                "memory": True,
                "allow_delegation": False,
                "allow_code_execution": False,
                "respect_context_window": True,
                "knowledge_collection": None,
                "tools": {"PythonCodeTool": [], "MCPTool": []},
                "realtime_agent": None,
                "naive_search_config": None,
            }
        ],
    }


class TestV2ToV3:
    def _convert(self, bundle):
        return v2_to_v3(copy.deepcopy(bundle))

    def test_trivial_crew_node_converted_to_agent_node(self):
        result = self._convert(_trivial_crew_bundle())
        node = result["Flow"][0]["nodes"][0]

        assert node["id"] == 100
        assert node["node_type"] == "AgentNode"
        assert node["graph"] == 10
        assert node["node_name"] == "Crew Node #1"
        assert node["surface_list"] == []
        assert node["inline_surface"] is None
        assert node["agent_definition"] == 300

    def test_trivial_crew_node_creates_agent_definition(self):
        result = self._convert(_trivial_crew_bundle())
        agent_definitions = result["AgentDefinition"]

        assert len(agent_definitions) == 1
        agent_definition = agent_definitions[0]
        assert agent_definition["id"] == 300
        assert agent_definition["description"] == "Senior Researcher"
        assert agent_definition["instructions"] == (
            "Find accurate information\n\nYears of experience in research"
        )
        assert agent_definition["llm_config"] == 5
        assert agent_definition["fcm_llm_config"] is None
        assert agent_definition["max_iter"] == 15
        assert agent_definition["max_rpm"] == 50
        assert agent_definition["cache"] is True
        assert agent_definition["max_retry_limit"] == 3
        assert agent_definition["default_temperature"] == 0.5
        assert agent_definition["max_execution_time"] is None
        assert agent_definition["owned_surfaces"] == []
        assert agent_definition["default_surfaces"] == []

    def test_trivial_crew_node_tasks_built_in_order_with_context(self):
        result = self._convert(_trivial_crew_bundle())
        node = result["Flow"][0]["nodes"][0]
        tasks = node["tasks"]

        assert [task["id"] for task in tasks] == [1, 2]
        assert tasks[0]["instructions"] == (
            "Research the topic\n\nExpected output: A research summary"
        )
        assert tasks[0]["context_tasks"] == []
        assert tasks[1]["instructions"] == "Write the report"
        assert tasks[1]["context_tasks"] == [1]
        assert tasks[1]["output_schema"] == {}

    def test_task_with_null_order_resolves_to_valid_non_null_int(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"][0]["order"] = 5
        bundle["Project"][0]["tasks"][1]["order"] = None

        result = self._convert(bundle)
        node = result["Flow"][0]["nodes"][0]
        tasks = node["tasks"]

        for task in tasks:
            assert task["order"] is not None
            assert isinstance(task["order"], int)

        # order is the dense sorted-list position, so it's always non-null and unique.
        order_values = [task["order"] for task in tasks]
        assert order_values == sorted(set(order_values))
        assert order_values == list(range(len(tasks)))

        # order=None task (id=2) sorts before order=5 task (id=1) by original list position.
        assert [task["id"] for task in tasks] == [2, 1]
        assert tasks[0]["order"] == 0
        assert tasks[1]["order"] == 1

        # id=2's forward reference to id=1 (now higher order) is dropped.
        tasks_by_id = {task["id"]: task for task in tasks}
        for task in tasks:
            for context_id in task["context_tasks"]:
                assert tasks_by_id[context_id]["order"] < task["order"]
        assert tasks_by_id[2]["context_tasks"] == []

    def test_context_tasks_drops_reference_with_non_strictly_lower_resolved_order(
        self,
    ):
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
                            "input_map": {},
                            "output_variable_path": "result",
                            "metadata": {},
                            "crew": 200,
                        }
                    ],
                }
            ],
            "Project": [
                {
                    "id": 200,
                    "name": "Crew",
                    "process": "sequential",
                    "tasks": [
                        # invalidly references id=30, which sorts after it.
                        {
                            "id": 10,
                            "name": "First",
                            "agent": 300,
                            "instructions": "Do first",
                            "expected_output": None,
                            "order": None,
                            "context": [30],
                        },
                        # validly references id=10, sorted before it.
                        {
                            "id": 20,
                            "name": "Second",
                            "agent": 300,
                            "instructions": "Do second",
                            "expected_output": None,
                            "order": None,
                            "context": [10],
                        },
                        {
                            "id": 30,
                            "name": "Third",
                            "agent": 300,
                            "instructions": "Do third",
                            "expected_output": None,
                            "order": None,
                            "context": [],
                        },
                    ],
                }
            ],
            "Agent": [
                {
                    "id": 300,
                    "role": "Worker",
                    "goal": "Get things done",
                    "backstory": "Reliable",
                    "llm_config": None,
                    "fcm_llm_config": None,
                    "max_iter": None,
                    "max_rpm": None,
                    "max_execution_time": None,
                    "cache": None,
                    "max_retry_limit": None,
                    "default_temperature": None,
                }
            ],
        }

        result = self._convert(bundle)
        node = result["Flow"][0]["nodes"][0]
        tasks_by_id = {task["id"]: task for task in node["tasks"]}

        assert tasks_by_id[10]["order"] == 0
        assert tasks_by_id[20]["order"] == 1
        assert tasks_by_id[30]["order"] == 2

        # id=10 -> id=30 is a forward reference — dropped.
        assert tasks_by_id[10]["context_tasks"] == []
        # id=20 -> id=10 is a valid backward reference — kept.
        assert tasks_by_id[20]["context_tasks"] == [10]
        assert tasks_by_id[30]["context_tasks"] == []

    def test_trivial_crew_node_tasks_drop_unsupported_fields(self):
        result = self._convert(_trivial_crew_bundle())
        node = result["Flow"][0]["nodes"][0]

        for task in node["tasks"]:
            assert "knowledge_query" not in task
            assert "human_input" not in task
            assert "async_execution" not in task
            assert "config" not in task

    def test_multi_agent_crew_node_left_untouched(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"][1]["agent"] = 301
        bundle["Agent"].append(
            {
                "id": 301,
                "role": "Writer",
                "goal": "Write well",
                "backstory": "A great writer",
                "llm_config": None,
                "fcm_llm_config": None,
                "max_iter": None,
                "max_rpm": None,
                "max_execution_time": None,
                "cache": None,
                "max_retry_limit": None,
                "default_temperature": None,
            }
        )
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node == original_node
        assert "AgentDefinition" not in result

    def test_crew_node_with_stray_manager_llm_config_and_sequential_process_converted(
        self,
    ):
        # manager_llm_config only takes effect when process="hierarchical".
        # A leftover/default value with process="sequential" must not block
        # the trivial-crew conversion.
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["manager_llm_config"] = 7

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node["node_type"] == "AgentNode"
        assert node["agent_definition"] == 300
        assert len(result["AgentDefinition"]) == 1

    def test_hierarchical_crew_node_left_untouched(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["process"] = "hierarchical"
        bundle["Project"][0]["manager_llm_config"] = 7
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node == original_node
        assert "AgentDefinition" not in result

    def test_crew_node_with_stray_memory_llm_config_and_embedding_config_converted(
        self,
    ):
        # memory_llm_config/embedding_config only take effect when
        # memory=True. Leftover/default values with memory=False must not
        # block the trivial-crew conversion (regression test for a real
        # import that was wrongly skipped).
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["memory"] = False
        bundle["Project"][0]["memory_llm_config"] = 2
        bundle["Project"][0]["embedding_config"] = 2

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node["node_type"] == "AgentNode"
        assert node["agent_definition"] == 300
        assert len(result["AgentDefinition"]) == 1

    def test_crew_node_with_memory_enabled_left_untouched(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["memory"] = True
        bundle["Project"][0]["memory_llm_config"] = 2
        bundle["Project"][0]["embedding_config"] = 2
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node == original_node
        assert "AgentDefinition" not in result

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

    def test_crew_node_with_missing_crew_left_unconverted(self):
        bundle = _trivial_crew_bundle()
        bundle["Flow"][0]["nodes"][0]["crew"] = 999
        original_node = copy.deepcopy(bundle["Flow"][0]["nodes"][0])

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node == original_node
        assert node["node_type"] == "CrewNode"

    def test_task_with_missing_agent_leaves_agent_definition_none(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"][0]["agent"] = 999
        bundle["Project"][0]["tasks"][1]["agent"] = 999

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node["node_type"] == "AgentNode"
        assert node["agent_definition"] is None
        assert "AgentDefinition" not in result

    def test_crew_with_no_tasks_converts_to_agent_node_with_empty_tasks(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"] = []

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        assert node["node_type"] == "AgentNode"
        assert node["agent_definition"] is None
        assert node["tasks"] == []
        assert "AgentDefinition" not in result

    def test_duplicate_legacy_task_names_disambiguated(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"][0]["name"] = "Same Name"
        bundle["Project"][0]["tasks"][1]["name"] = "Same Name"
        bundle["Project"][0]["tasks"][1]["context"] = []

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        names = [task["name"] for task in node["tasks"]]
        assert names == ["Same Name", "Same Name (2)"]
        assert len(set(names)) == len(names)

    def test_duplicate_legacy_task_name_not_collided_with_preexisting_name(self):
        bundle = _trivial_crew_bundle()
        bundle["Project"][0]["tasks"][0]["name"] = "Research"
        bundle["Project"][0]["tasks"][1]["name"] = "Research"
        bundle["Project"][0]["tasks"][1]["context"] = []
        bundle["Project"][0]["tasks"].append(
            {
                "id": 3,
                "name": "Research (2)",
                "agent": 300,
                "instructions": "Double check the research",
                "expected_output": None,
                "order": 3,
                "context": [],
                "knowledge_query": None,
                "human_input": False,
                "async_execution": False,
                "config": None,
            }
        )

        result = self._convert(bundle)

        node = result["Flow"][0]["nodes"][0]
        names = [task["name"] for task in node["tasks"]]
        assert names == ["Research", "Research (3)", "Research (2)"]
        assert len(set(names)) == len(names)

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
