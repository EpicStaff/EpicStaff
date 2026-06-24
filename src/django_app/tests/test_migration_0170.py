"""
Tests for the migrate_to_variables data migration (0170).

Uses mock objects instead of MigrationExecutor because PythonCodeToolConfigField
no longer exists in the schema after the migration was applied.
"""

import importlib
from unittest.mock import MagicMock, patch

import pytest

migration = importlib.import_module(
    "tables.migrations.0170_pythoncodetool_variables_drop_args_schema"
)
migrate_to_variables = migration.migrate_to_variables
_FIELD_TYPE_TO_VAR_TYPE = migration._FIELD_TYPE_TO_VAR_TYPE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(args_schema=None, config_fields=None):
    """Return a mock PythonCodeTool with the pre-migration shape."""
    tool = MagicMock()
    tool.args_schema = args_schema
    tool.variables = []

    fields_qs = MagicMock()
    fields_qs.__iter__ = MagicMock(return_value=iter(config_fields or []))
    tool._config_fields = config_fields or []
    return tool


def _make_config_field(name, data_type, required=False, description=""):
    f = MagicMock()
    f.name = name
    f.data_type = data_type
    f.required = required
    f.description = description
    return f


def _run_migration(tools, config_fields_by_tool=None):
    """
    Call migrate_to_variables with a mock apps object.
    config_fields_by_tool: dict mapping tool mock → list of field mocks.
    """
    config_fields_by_tool = config_fields_by_tool or {}

    MockTool = MagicMock()
    MockTool.objects.all.return_value = tools

    MockField = MagicMock()

    def filter_fields(tool):
        fields = config_fields_by_tool.get(tool, [])
        qs = MagicMock()
        qs.__iter__ = MagicMock(return_value=iter(fields))
        return qs

    MockField.objects.filter = lambda tool: filter_fields(tool)

    apps = MagicMock()
    apps.get_model.side_effect = lambda app, name: (
        MockTool if name == "PythonCodeTool" else MockField
    )

    migrate_to_variables(apps, schema_editor=MagicMock())
    return tools


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_args_schema_and_no_fields():
    """Tool with no args_schema and no config fields → variables stays empty."""
    tool = _make_tool(args_schema=None)
    _run_migration([tool])
    assert tool.variables == []
    tool.save.assert_called_once_with(update_fields=["variables"])


def test_args_schema_properties_become_agent_input():
    """args_schema properties → agent_input variables."""
    tool = _make_tool(args_schema={
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results", "default": 10},
        },
        "required": ["query"],
    })
    _run_migration([tool])

    by_name = {v["name"]: v for v in tool.variables}
    assert len(tool.variables) == 2

    q = by_name["query"]
    assert q["input_type"] == "agent_input"
    assert q["type"] == "string"
    assert q["required"] is True
    assert q["default_value"] is None

    lim = by_name["limit"]
    assert lim["input_type"] == "agent_input"
    assert lim["type"] == "integer"
    assert lim["required"] is False
    assert lim["default_value"] == 10


def test_config_fields_become_user_input():
    """PythonCodeToolConfigField records → user_input variables."""
    tool = _make_tool(args_schema=None)
    fields = [
        _make_config_field("api_key", "string", required=True, description="API key"),
        _make_config_field("timeout", "integer", required=False),
    ]
    _run_migration([tool], {tool: fields})

    by_name = {v["name"]: v for v in tool.variables}
    assert len(tool.variables) == 2

    assert by_name["api_key"]["input_type"] == "user_input"
    assert by_name["api_key"]["type"] == "string"
    assert by_name["api_key"]["required"] is True
    assert by_name["api_key"]["description"] == "API key"
    assert by_name["api_key"]["default_value"] is None

    assert by_name["timeout"]["input_type"] == "user_input"
    assert by_name["timeout"]["type"] == "integer"
    assert by_name["timeout"]["required"] is False


def test_args_schema_and_config_fields_merged():
    """Tool with both args_schema and config fields → merged list, agent_input first."""
    tool = _make_tool(args_schema={
        "properties": {"query": {"type": "string", "description": "Query"}},
        "required": ["query"],
    })
    fields = [_make_config_field("api_key", "string", required=True)]
    _run_migration([tool], {tool: fields})

    assert len(tool.variables) == 2
    names = [v["name"] for v in tool.variables]
    assert names.index("query") < names.index("api_key")

    by_name = {v["name"]: v for v in tool.variables}
    assert by_name["query"]["input_type"] == "agent_input"
    assert by_name["api_key"]["input_type"] == "user_input"


def test_field_type_mapping():
    """All _FIELD_TYPE_TO_VAR_TYPE entries are applied correctly."""
    type_cases = [
        ("llm_config", "integer"),
        ("embedding_config", "integer"),
        ("string", "string"),
        ("boolean", "boolean"),
        ("any", "any"),
        ("integer", "integer"),
        ("float", "number"),
    ]
    for data_type, expected_var_type in type_cases:
        tool = _make_tool(args_schema=None)
        fields = [_make_config_field("x", data_type)]
        _run_migration([tool], {tool: fields})
        assert tool.variables[0]["type"] == expected_var_type, (
            f"data_type={data_type!r} should map to {expected_var_type!r}"
        )


def test_nested_object_properties_preserved():
    """args_schema with nested object properties → properties + required_properties kept."""
    tool = _make_tool(args_schema={
        "properties": {
            "person": {
                "type": "object",
                "description": "Person",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                },
                "required": ["first_name", "last_name"],
            }
        },
        "required": [],
    })
    _run_migration([tool])

    var = tool.variables[0]
    assert var["name"] == "person"
    assert var["type"] == "object"
    assert var["properties"] == {
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
    }
    assert var["required_properties"] == ["first_name", "last_name"]


def test_array_items_preserved():
    """args_schema with array type → items schema kept."""
    tool = _make_tool(args_schema={
        "properties": {
            "tags": {
                "type": "array",
                "description": "Tags",
                "items": {"type": "string"},
            }
        },
        "required": ["tags"],
    })
    _run_migration([tool])

    var = tool.variables[0]
    assert var["name"] == "tags"
    assert var["type"] == "array"
    assert var["items"] == {"type": "string"}
    assert "properties" not in var


def test_multiple_tools_processed_independently():
    """Each tool gets its own variables; no cross-contamination."""
    tool_a = _make_tool(args_schema={
        "properties": {"x": {"type": "string", "description": ""}},
        "required": ["x"],
    })
    tool_b = _make_tool(args_schema=None)
    fields_b = [_make_config_field("secret", "string", required=True)]

    _run_migration([tool_a, tool_b], {tool_b: fields_b})

    assert len(tool_a.variables) == 1
    assert tool_a.variables[0]["name"] == "x"

    assert len(tool_b.variables) == 1
    assert tool_b.variables[0]["name"] == "secret"
