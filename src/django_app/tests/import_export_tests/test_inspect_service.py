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
            "conditional_edge_list": [],
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
            "conditional_edge_list": [],
        }
    ],
    "main_entity": "Flow",
    "version": 2,
}

FLOW_WITH_CONDITIONAL_EDGE_EXPORT = {
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
            "conditional_edge_list": [],
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


class TestInspectServiceConditionalEdge:
    def test_conditional_edge_surfaced(self):
        result = InspectService().inspect(FLOW_WITH_CONDITIONAL_EDGE_EXPORT)
        assert len(result["review_items"]) == 1
        item = result["review_items"][0]
        assert item["kind"] == "flow_node"
        assert item["node_type"] == "ConditionalEdge"
        assert item["node_name"] is None
        assert item["flow_name"] == "conditional_flow"
        assert "python_code" in item


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
            "Flow": [{"id": 1, "name": "empty", "nodes": [], "conditional_edge_list": []}],
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
