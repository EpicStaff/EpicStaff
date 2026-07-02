import pytest
from unittest.mock import MagicMock
from tables.exceptions import PythonCodeToolConfigSerializerError
from tables.models.python_models import PythonCodeTool
from tables.validators.python_code_tool_config_validator import (
    PythonCodeToolConfigValidator,
)


def make_tool(variables):
    tool = MagicMock(spec=PythonCodeTool)
    tool.variables = variables
    return tool


@pytest.fixture
def validator():
    return PythonCodeToolConfigValidator()


def test_validate_invalid_configuration_type(validator):
    tool = make_tool([])
    with pytest.raises(PythonCodeToolConfigSerializerError, match="must be an object"):
        validator.validate("test_tool", tool, configuration=[1, 2, 3])


def test_validate_happy_path_string(validator):
    tool = make_tool(
        [{"name": "api_key", "type": "string", "input_type": "user_input", "required": True}]
    )
    result = validator.validate("tool", tool, {"api_key": "secret_123"})
    assert result["api_key"] == "secret_123"


def test_validate_missing_required_field_raises_error(validator):
    tool = make_tool(
        [{"name": "api_key", "type": "string", "input_type": "user_input", "required": True}]
    )
    with pytest.raises(
        PythonCodeToolConfigSerializerError, match="Field 'api_key' is required"
    ):
        validator.validate("tool", tool, {})


def test_validate_missing_required_field_allowed_flag():
    validator = PythonCodeToolConfigValidator(validate_missing_required_fields=False)
    tool = make_tool(
        [{"name": "api_key", "type": "string", "input_type": "user_input", "required": True}]
    )
    result = validator.validate("tool", tool, {})
    assert result["api_key"] is None


def test_validate_ignores_extra_config_fields(validator):
    tool = make_tool([])
    result = validator.validate("tool", tool, {"random_extra_field": "should_be_ignored"})
    assert "random_extra_field" not in result
    assert result == {}


def test_validate_rejects_agent_input_field(validator):
    tool = make_tool(
        [{"name": "query", "type": "string", "input_type": "agent_input", "required": True}]
    )
    with pytest.raises(PythonCodeToolConfigSerializerError, match="set by the agent"):
        validator.validate("tool", tool, {"query": "something"})


def test_validate_mixed_variable_accepted(validator):
    tool = make_tool(
        [{"name": "limit", "type": "integer", "input_type": "mixed", "required": False}]
    )
    result = validator.validate("tool", tool, {"limit": 5})
    assert result["limit"] == 5


@pytest.mark.parametrize(
    "var_type, input_val, expected_val",
    [
        ("integer", "10", 10),
        ("integer", 10, 10),
        ("number", "10.5", 10.5),
        ("number", 10, 10.0),
        ("string", 123, "123"),
        ("boolean", True, True),
        ("boolean", False, False),
        ("any", {"a": 1}, {"a": 1}),
    ],
)
def test_casting_success(validator, var_type, input_val, expected_val):
    tool = make_tool(
        [{"name": "field", "type": var_type, "input_type": "user_input", "required": True}]
    )
    result = validator.validate("tool", tool, {"field": input_val})
    assert result["field"] == expected_val


def test_casting_failure_raises_error(validator):
    tool = make_tool(
        [{"name": "max_tokens", "type": "integer", "input_type": "user_input", "required": True}]
    )
    with pytest.raises(PythonCodeToolConfigSerializerError, match="Error casting value"):
        validator.validate("tool", tool, {"max_tokens": "not_a_number"})


def test_validate_none_value_not_cast():
    validator = PythonCodeToolConfigValidator(validate_missing_required_fields=False)
    tool = make_tool(
        [{"name": "count", "type": "integer", "input_type": "user_input", "required": True}]
    )
    result = validator.validate("tool", tool, {})
    assert result["count"] is None


def test_validate_nested_object(validator):
    tool = make_tool([
        {
            "name": "settings",
            "type": "object",
            "input_type": "user_input",
            "required": True,
            "properties": {
                "api_key": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required_properties": ["api_key"],
        }
    ])
    result = validator.validate("tool", tool, {
        "settings": {"api_key": "abc", "timeout": "30"}
    })
    assert result["settings"]["api_key"] == "abc"
    assert result["settings"]["timeout"] == 30


def test_validate_nested_object_missing_required(validator):
    tool = make_tool([
        {
            "name": "settings",
            "type": "object",
            "input_type": "user_input",
            "required": True,
            "properties": {
                "api_key": {"type": "string"},
            },
            "required_properties": ["api_key"],
        }
    ])
    with pytest.raises(PythonCodeToolConfigSerializerError, match="api_key.*required"):
        validator.validate("tool", tool, {"settings": {}})


def test_validate_nested_object_wrong_type(validator):
    tool = make_tool([
        {
            "name": "settings",
            "type": "object",
            "input_type": "user_input",
            "required": True,
            "properties": {"count": {"type": "integer"}},
            "required_properties": [],
        }
    ])
    with pytest.raises(PythonCodeToolConfigSerializerError, match="Expected an object"):
        validator.validate("tool", tool, {"settings": "not_an_object"})


def test_validate_array_with_items(validator):
    tool = make_tool([
        {
            "name": "tags",
            "type": "array",
            "input_type": "user_input",
            "required": False,
            "items": {"type": "string"},
        }
    ])
    result = validator.validate("tool", tool, {"tags": ["a", "b", "c"]})
    assert result["tags"] == ["a", "b", "c"]


def test_validate_array_wrong_type(validator):
    tool = make_tool([
        {
            "name": "ids",
            "type": "array",
            "input_type": "user_input",
            "required": False,
            "items": {"type": "integer"},
        }
    ])
    with pytest.raises(PythonCodeToolConfigSerializerError, match="Expected an array"):
        validator.validate("tool", tool, {"ids": "not_an_array"})


def test_validate_deeply_nested_object(validator):
    tool = make_tool([
        {
            "name": "config",
            "type": "object",
            "input_type": "user_input",
            "required": True,
            "properties": {
                "db": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                    },
                    "required": ["port"],
                },
            },
            "required_properties": ["db"],
        }
    ])
    result = validator.validate("tool", tool, {
        "config": {"db": {"port": "5432"}}
    })
    assert result["config"]["db"]["port"] == 5432
