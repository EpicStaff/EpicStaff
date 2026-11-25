"""
Integration-style tests for InspectService.

All tests exercise InspectService.inspect() directly (no DB required).
"""

import pytest

from tables.import_export.services.inspect_service import InspectService


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

PYTHON_CODE_TOOL_EXPORT = {
    "PythonCodeTool": [
        {
            "id": 1,
            "name": "tool_one",
            "description": "first tool",
            "python_code": {
                "code": "def main(): return {}",
                "libraries": "requests\nbeautifulsoup4",
                "entrypoint": "main",
                "global_kwargs": {},
            },
            "variables": [],
            "use_storage": False,
        },
        {
            "id": 2,
            "name": "tool_two",
            "description": "second tool",
            "python_code": {
                "code": "def main(): pass",
                "libraries": "",
                "entrypoint": "main",
                "global_kwargs": {},
            },
            "variables": [{"name": "x", "type": "string"}],
            "use_storage": True,
        },
    ],
    "main_entity": "PythonCodeTool",
    "version": 2,
}

MCP_TOOL_EXPORT = {
    "MCPTool": [
        {
            "id": 2,
            "name": "Custom mpc",
            "transport": "hello",
            "tool_name": "custom mpc",
            "timeout": 30.0,
            "init_timeout": 10.0,
            "org": 1,
            "labels": [],
        }
    ],
    "main_entity": "MCPTool",
    "version": 2,
}

FLOW_EXPORT = {
    "Flow": [
        {
            "id": 2,
            "name": "hello",
            "nodes": [
                {
                    "id": 7,
                    "python_code": {
                        "code": "def main(a, b): return a + b",
                        "libraries": "",
                        "entrypoint": "main",
                        "global_kwargs": {},
                    },
                    "node_name": "Python-Node #2",
                    "node_type": "PythonNode",
                },
                {
                    "id": 10,
                    "python_code": {
                        "code": "def main(trigger_payload, **kwargs): return {}",
                        "libraries": "",
                        "entrypoint": "main",
                        "global_kwargs": {},
                    },
                    "node_name": "Webhook Trigger #3",
                    "node_type": "WebhookTriggerNode",
                },
                {
                    "id": 9,
                    "condition_groups": [],
                    "node_name": "Decision-Table #6",
                    "node_type": "DecisionTableNode",
                },
            ],
        }
    ],
    "main_entity": "Flow",
    "version": 2,
}

FLOW_WITH_CLASSIFICATION_NODE_EXPORT = {
    "Flow": [
        {
            "id": 3,
            "name": "classification_flow",
            "nodes": [
                {
                    "id": 20,
                    "pre_python_code": {
                        "code": "def pre(): return {}",
                        "libraries": "",
                        "entrypoint": "pre",
                        "global_kwargs": {},
                    },
                    "post_python_code": {
                        "code": "def post(): return {}",
                        "libraries": "",
                        "entrypoint": "post",
                        "global_kwargs": {},
                    },
                    "node_name": "Classify #1",
                    "node_type": "ClassificationDecisionTableNode",
                },
            ],
        }
    ],
    "main_entity": "Flow",
    "version": 2,
}

LEGACY_FLOW_WITH_CONDITIONAL_EDGE_EXPORT = {
    "Flow": [
        {
            "id": 4,
            "name": "conditional_flow",
            "nodes": [],
            "conditional_edge_list": [
                {
                    "id": 30,
                    "python_code": {
                        "code": "def condition(): return True",
                        "libraries": "",
                        "entrypoint": "condition",
                        "global_kwargs": {},
                    },
                },
            ],
        }
    ],
    "main_entity": "Flow",
    "version": 2,
}

FLOW_WITH_NESTED_PYTHON_TOOL_EXPORT = {
    "Flow": [
        {
            "id": 5,
            "name": "flow_with_tool",
            "nodes": [
                {
                    "id": 40,
                    "python_code": {
                        "code": "def main(): return {}",
                        "libraries": "",
                        "entrypoint": "main",
                        "global_kwargs": {},
                    },
                    "node_name": "Python Node",
                    "node_type": "PythonNode",
                }
            ],
        }
    ],
    "PythonCodeTool": [
        {
            "id": 99,
            "name": "bundled_tool",
            "description": "a tool bundled with the flow",
            "python_code": {
                "code": "def main(): return {}",
                "libraries": "numpy",
                "entrypoint": "main",
                "global_kwargs": {},
            },
            "variables": [],
            "use_storage": False,
        }
    ],
    "main_entity": "Flow",
    "version": 2,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInspectServicePythonCodeTool:
    def test_returns_two_items(self):
        result = InspectService().inspect(PYTHON_CODE_TOOL_EXPORT)
        assert len(result["review_items"]) == 2

    def test_item_kind(self):
        result = InspectService().inspect(PYTHON_CODE_TOOL_EXPORT)
        for item in result["review_items"]:
            assert item["kind"] == "python_code_tool"

    def test_item_fields_present(self):
        result = InspectService().inspect(PYTHON_CODE_TOOL_EXPORT)
        item = result["review_items"][0]
        assert item["name"] == "tool_one"
        assert item["description"] == "first tool"
        assert item["python_code"]["code"] == "def main(): return {}"
        assert item["variables"] == []
        assert item["use_storage"] is False

    def test_libraries_preserved_as_raw_string(self):
        result = InspectService().inspect(PYTHON_CODE_TOOL_EXPORT)
        item = result["review_items"][0]
        # libraries must be the raw string from the export — NOT split into an array
        assert item["python_code"]["libraries"] == "requests\nbeautifulsoup4"


class TestInspectServiceMcpTool:
    def test_returns_one_item(self):
        result = InspectService().inspect(MCP_TOOL_EXPORT)
        assert len(result["review_items"]) == 1

    def test_item_kind(self):
        result = InspectService().inspect(MCP_TOOL_EXPORT)
        assert result["review_items"][0]["kind"] == "mcp_tool"

    def test_only_name_and_transport_present(self):
        result = InspectService().inspect(MCP_TOOL_EXPORT)
        item = result["review_items"][0]
        assert item["name"] == "Custom mpc"
        assert item["transport"] == "hello"
        assert "tool_name" not in item
        assert "timeout" not in item
        assert "init_timeout" not in item


class TestInspectServiceFlowNodes:
    def test_python_node_and_webhook_node_surfaced(self):
        result = InspectService().inspect(FLOW_EXPORT)
        items = result["review_items"]
        node_types = {item["node_type"] for item in items}
        assert "PythonNode" in node_types
        assert "WebhookTriggerNode" in node_types

    def test_decision_table_node_excluded(self):
        result = InspectService().inspect(FLOW_EXPORT)
        items = result["review_items"]
        node_types = {item["node_type"] for item in items}
        assert "DecisionTableNode" not in node_types

    def test_flow_node_fields(self):
        result = InspectService().inspect(FLOW_EXPORT)
        python_items = [i for i in result["review_items"] if i["node_type"] == "PythonNode"]
        assert len(python_items) == 1
        item = python_items[0]
        assert item["kind"] == "flow_node"
        assert item["flow_name"] == "hello"
        assert item["node_name"] == "Python-Node #2"
        assert "python_code" in item

    def test_exactly_two_code_nodes(self):
        result = InspectService().inspect(FLOW_EXPORT)
        assert len(result["review_items"]) == 2

    def test_nodes_sharing_a_name_are_told_apart_by_file_node_id(self):
        python_code = {
            "code": "def main(): return {}",
            "libraries": "",
            "entrypoint": "main",
            "global_kwargs": {},
        }
        data = {
            "Flow": [
                {
                    "id": 1,
                    "name": "duplicate_names",
                    "nodes": [
                        {
                            "id": 31,
                            "python_code": python_code,
                            "node_name": "Python Node",
                            "node_type": "PythonNode",
                        },
                        {
                            "id": 58,
                            "python_code": python_code,
                            "node_name": "Python Node",
                            "node_type": "PythonNode",
                        },
                    ],
                }
            ],
            "main_entity": "Flow",
            "version": 2,
        }

        items = InspectService().inspect(data)["review_items"]

        assert [item["node_name"] for item in items] == ["Python Node", "Python Node"]
        assert [item["node_id"] for item in items] == [31, 58]

    @pytest.mark.parametrize("file_id", ["31", True, False, 31.0, None])
    def test_node_id_is_none_when_file_id_is_not_an_integer(self, file_id):
        data = {
            "Flow": [
                {
                    "id": 1,
                    "name": "hand_made",
                    "nodes": [
                        {
                            "id": file_id,
                            "python_code": {
                                "code": "def main(): return {}",
                                "libraries": "",
                                "entrypoint": "main",
                                "global_kwargs": {},
                            },
                            "node_name": "Python Node",
                            "node_type": "PythonNode",
                        },
                    ],
                }
            ],
            "main_entity": "Flow",
            "version": 2,
        }

        items = InspectService().inspect(data)["review_items"]

        assert len(items) == 1
        assert items[0]["node_id"] is None


class TestInspectServiceClassificationNode:
    def test_classification_node_carries_both_code_keys(self):
        result = InspectService().inspect(FLOW_WITH_CLASSIFICATION_NODE_EXPORT)
        assert len(result["review_items"]) == 1
        item = result["review_items"][0]
        assert item["kind"] == "flow_node"
        assert item["node_type"] == "ClassificationDecisionTableNode"
        assert "pre_python_code" in item
        assert "post_python_code" in item
        assert item["pre_python_code"]["code"] == "def pre(): return {}"
        assert item["post_python_code"]["code"] == "def post(): return {}"


class TestInspectServiceLegacyConditionalEdge:
    def test_conditional_edge_code_is_not_surfaced(self):
        """Import discards conditional edges, so their code never runs and is not reviewed."""
        result = InspectService().inspect(LEGACY_FLOW_WITH_CONDITIONAL_EDGE_EXPORT)
        assert result["review_items"] == []


class TestInspectServiceNestedEntities:
    def test_bundled_python_tool_surfaced_alongside_flow_nodes(self):
        result = InspectService().inspect(FLOW_WITH_NESTED_PYTHON_TOOL_EXPORT)
        kinds = [item["kind"] for item in result["review_items"]]
        assert "python_code_tool" in kinds
        assert "flow_node" in kinds

    def test_both_items_present(self):
        result = InspectService().inspect(FLOW_WITH_NESTED_PYTHON_TOOL_EXPORT)
        assert len(result["review_items"]) == 2

    def test_nested_tool_libraries_preserved(self):
        result = InspectService().inspect(FLOW_WITH_NESTED_PYTHON_TOOL_EXPORT)
        tool_items = [i for i in result["review_items"] if i["kind"] == "python_code_tool"]
        assert tool_items[0]["python_code"]["libraries"] == "numpy"


class TestInspectServiceEdgeCases:
    def test_empty_flow_returns_empty_list(self):
        data = {
            "Flow": [{"id": 1, "name": "empty", "nodes": []}],
            "main_entity": "Flow",
            "version": 2,
        }
        result = InspectService().inspect(data)
        assert result == {"review_items": []}

    def test_unknown_entity_type_ignored(self):
        data = {
            "UnknownEntity": [{"id": 1, "name": "x"}],
            "main_entity": "UnknownEntity",
            "version": 2,
        }
        result = InspectService().inspect(data)
        assert result == {"review_items": []}

    def test_meta_keys_skipped(self):
        data = {
            "main_entity": "PythonCodeTool",
            "version": 2,
            "PythonCodeTool": [],
        }
        result = InspectService().inspect(data)
        assert result == {"review_items": []}


def _flow_with_nodes(*nodes) -> dict:
    return {
        "Flow": [{"id": 1, "name": "flow", "nodes": list(nodes)}],
        "main_entity": "Flow",
        "version": 6,
    }


class TestInspectServiceDecisionTableExpressions:
    def test_decision_table_expressions_are_listed_in_order(self):
        node = {
            "id": 11,
            "node_name": "Router",
            "node_type": "DecisionTableNode",
            "condition_groups": [
                {
                    "group_name": "big",
                    "expression": "variables['a'] > 1",
                    "manipulation": "variables['b'] = 2",
                    "conditions": [
                        {"condition_name": "first", "condition": "variables['x'] == 1"},
                        {"condition_name": "second", "condition": "variables['y'] == 2"},
                    ],
                },
            ],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["node_id"] == 11
        assert item["expressions"] == [
            {"label": 'Group "big": expression', "code": "variables['a'] > 1"},
            {"label": 'Group "big": manipulation', "code": "variables['b'] = 2"},
            {"label": 'Group "big", condition "first"', "code": "variables['x'] == 1"},
            {"label": 'Group "big", condition "second"', "code": "variables['y'] == 2"},
        ]

    def test_classification_table_lists_code_and_expressions_in_one_item(self):
        pre_python_code = {"code": "def pre(): return {}", "entrypoint": "pre"}
        node = {
            "id": 12,
            "node_name": "Classify",
            "node_type": "ClassificationDecisionTableNode",
            "pre_python_code": pre_python_code,
            "condition_groups": [
                {
                    "group_name": "first",
                    "expression": "score > 5",
                    "manipulation": "variables.seen = True",
                    "field_expressions": {"status": "== 'open'", "level": "> 2"},
                    "field_manipulations": {"result": "'high'"},
                },
                {"group_name": "second", "field_expressions": {"kind": "'bug'"}},
            ],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["pre_python_code"] == pre_python_code
        assert item["expressions"] == [
            {"label": 'Group "first": expression', "code": "score > 5"},
            {"label": 'Group "first": manipulation', "code": "variables.seen = True"},
            {"label": 'Group "first": field expression', "code": "status == 'open'"},
            {"label": 'Group "first": field expression', "code": "level > 2"},
            {"label": 'Group "first": field manipulation', "code": "result = 'high'"},
            {"label": 'Group "second": field expression', "code": "kind 'bug'"},
        ]

    @pytest.mark.parametrize(
        ("fields_key", "value", "expected_code"),
        [
            ("field_expressions", "== 1", 'x\nimport os\nos.system("id")\ny == 1'),
            ("field_manipulations", "1", 'x\nimport os\nos.system("id")\ny = 1'),
        ],
    )
    def test_a_multi_line_field_name_is_shown_verbatim_in_the_code(
        self, fields_key, value, expected_code
    ):
        field_name = 'x\nimport os\nos.system("id")\ny'
        node = {
            "id": 19,
            "node_type": "ClassificationDecisionTableNode",
            "condition_groups": [{"group_name": "g", fields_key: {field_name: value}}],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        [expression] = item["expressions"]
        assert expression["code"] == expected_code

    @pytest.mark.parametrize("empty_value", [None, "", "   \n\t"])
    def test_empty_values_give_no_entries_and_no_item(self, empty_value):
        node = {
            "id": 13,
            "node_type": "ClassificationDecisionTableNode",
            "condition_groups": [
                {
                    "group_name": "g",
                    "expression": empty_value,
                    "manipulation": empty_value,
                    "conditions": [{"condition_name": "c", "condition": empty_value}],
                    "field_expressions": {"f": empty_value},
                    "field_manipulations": {"m": empty_value},
                }
            ],
        }

        assert InspectService().inspect(_flow_with_nodes(node))["review_items"] == []

    def test_empty_values_are_skipped_next_to_real_ones(self):
        node = {
            "id": 14,
            "node_type": "DecisionTableNode",
            "condition_groups": [
                {"group_name": "g", "expression": " ", "manipulation": "x = 1", "conditions": []}
            ],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["expressions"] == [{"label": 'Group "g": manipulation', "code": "x = 1"}]

    def test_non_string_values_and_names_are_shown_as_text(self):
        node = {
            "id": 15,
            "node_type": "DecisionTableNode",
            "condition_groups": [
                {
                    "group_name": 7,
                    "expression": 0,
                    "conditions": [{"condition_name": 3, "condition": 42}],
                },
                {"expression": "True", "conditions": [{"condition": "False"}]},
            ],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["expressions"] == [
            {"label": 'Group "7": expression', "code": "0"},
            {"label": 'Group "7", condition "3"', "code": "42"},
            {"label": 'Group "": expression', "code": "True"},
            {"label": 'Group "", condition ""', "code": "False"},
        ]

    @pytest.mark.parametrize(
        "condition_groups",
        [
            "variables['a'] > 1",
            5,
            [["not", "a", "group"]],
            [{"group_name": "g", "conditions": "x == 1"}],
            [{"group_name": "g", "conditions": ["x == 1", None]}],
            [{"group_name": "g", "field_expressions": ["x == 1"]}],
            [{"group_name": "g", "field_manipulations": "x = 1"}],
        ],
    )
    def test_malformed_condition_groups_give_no_item_and_do_not_raise(self, condition_groups):
        node = {"id": 16, "node_type": "DecisionTableNode", "condition_groups": condition_groups}

        assert InspectService().inspect(_flow_with_nodes(node))["review_items"] == []

    def test_a_malformed_group_does_not_hide_a_valid_one(self):
        node = {
            "id": 17,
            "node_type": "DecisionTableNode",
            "condition_groups": ["junk", {"group_name": "g", "expression": "a"}],
        }

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["expressions"] == [{"label": 'Group "g": expression', "code": "a"}]

    @pytest.mark.parametrize("node_type", ["DecisionTabelNode", "PythonNode", None, "missing"])
    def test_condition_groups_are_listed_whatever_the_node_type(self, node_type):
        node = {"id": 18, "condition_groups": [{"group_name": "g", "expression": "a"}]}
        if node_type != "missing":
            node["node_type"] = node_type

        [item] = InspectService().inspect(_flow_with_nodes(node))["review_items"]

        assert item["node_id"] == 18
        assert item["expressions"] == [{"label": 'Group "g": expression', "code": "a"}]


class TestInspectServiceMalformedEntries:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({"Flow": ["not a flow"]}, id="flow-entry-is-a-string"),
            pytest.param({"Flow": [None]}, id="flow-entry-is-null"),
            pytest.param({"Flow": [{"name": "f", "nodes": None}]}, id="nodes-is-null"),
            pytest.param({"Flow": [{"name": "f", "nodes": "PythonNode"}]}, id="nodes-is-a-string"),
            pytest.param({"Flow": [{"name": "f", "nodes": {"id": 1}}]}, id="nodes-is-a-dict"),
            pytest.param({"Flow": [{"name": "f", "nodes": ["node", 5]}]}, id="node-is-not-a-dict"),
            pytest.param({"PythonCodeTool": ["tool", None]}, id="python-tool-is-not-a-dict"),
            pytest.param({"MCPTool": [["tool"]]}, id="mcp-tool-is-not-a-dict"),
        ],
    )
    def test_a_malformed_entry_gives_no_item_and_does_not_raise(self, data):
        assert InspectService().inspect(data) == {"review_items": []}

    def test_a_malformed_entry_does_not_hide_a_valid_one(self):
        code = {"code": "def main(): ...", "entrypoint": "main"}
        data = {
            "Flow": [
                "junk",
                {"name": "f", "nodes": ["junk", {"id": 3, "python_code": code}]},
            ],
            "PythonCodeTool": [None, {"id": 4, "name": "tool", "python_code": code}],
        }

        items = InspectService().inspect(data)["review_items"]

        flow_item, tool_item = items
        assert flow_item["node_id"] == 3
        assert tool_item["name"] == "tool"
