from types import SimpleNamespace

import pytest

from tables.exceptions import PythonCodeToolConfigSerializerError
from tables.validators.python_code_tool_config_validator import (
    PythonCodeToolConfigValidator,
)

# Nothing below queries the ORM. But tests/conftest.py has an autouse
# `heal_builtin_roles` fixture that queries the Role table before every db test, and
# without a test that pulls in the `db` fixture, pytest-django never swaps the
# connection to the test database, so that query would hit the real dev database.
pytestmark = pytest.mark.django_db


def variable(name, var_type="string", input_type="user_input", required=True, **schema):
    return {"name": name, "type": var_type, "input_type": input_type, "required": required, **schema}


SETTINGS = variable(
    "settings", "object",
    properties={"api_key": {"type": "string"}, "timeout": {"type": "integer"}},
    required_properties=["api_key"],
)
DEEP_CONFIG = variable(
    "config", "object",
    properties={"db": {"type": "object", "properties": {"port": {"type": "integer"}}, "required": ["port"]}},
    required_properties=["db"],
)


def validate(variables, configuration, **options):
    tool = SimpleNamespace(variables=variables)
    return PythonCodeToolConfigValidator(**options).validate("tool", tool, configuration)


@pytest.mark.parametrize(
    ("variables", "configuration", "expected"),
    [
        ([variable("api_key")], {"api_key": "secret_123"}, {"api_key": "secret_123"}),
        ([], {"random_extra_field": "ignored"}, {}),
        ([variable("limit", "integer", "mixed", required=False)], {"limit": 5}, {"limit": 5}),
        ([variable("field", "integer")], {"field": "10"}, {"field": 10}),
        ([variable("field", "integer")], {"field": 10}, {"field": 10}),
        ([variable("field", "number")], {"field": "10.5"}, {"field": 10.5}),
        ([variable("field", "number")], {"field": 10}, {"field": 10.0}),
        ([variable("field", "string")], {"field": 123}, {"field": "123"}),
        ([variable("field", "boolean")], {"field": True}, {"field": True}),
        ([variable("field", "boolean")], {"field": False}, {"field": False}),
        ([variable("field", "any")], {"field": {"a": 1}}, {"field": {"a": 1}}),
        ([SETTINGS], {"settings": {"api_key": "abc", "timeout": "30"}}, {"settings": {"api_key": "abc", "timeout": 30}}),
        ([variable("tags", "array", required=False, items={"type": "string"})], {"tags": ["a", "b"]}, {"tags": ["a", "b"]}),
        ([DEEP_CONFIG], {"config": {"db": {"port": "5432"}}}, {"config": {"db": {"port": 5432}}}),
    ],
    ids=[
        "string", "extra-field-dropped", "mixed-input", "integer-from-string", "integer", "number-from-string",
        "number-from-int", "string-from-int", "true", "false", "any", "nested-object-cast", "array", "deeply-nested-cast",
    ],
)
def test_a_valid_configuration_is_cast_to_the_declared_types(variables, configuration, expected):
    assert validate(variables, configuration) == expected


def test_missing_required_fields_can_be_left_for_later():
    """Drafts may be saved before every required field is filled in."""
    result = validate(
        [variable("api_key"), variable("count", "integer")], {}, validate_missing_required_fields=False
    )

    assert result == {"api_key": None, "count": None}


@pytest.mark.parametrize(
    ("variables", "configuration", "message"),
    [
        ([], [1, 2, 3], "must be an object"),
        ([variable("api_key")], {}, "Field 'api_key' is required"),
        ([variable("query", input_type="agent_input")], {"query": "something"}, "set by the agent"),
        ([variable("max_tokens", "integer")], {"max_tokens": "not_a_number"}, "Error casting value"),
        ([SETTINGS], {"settings": {}}, "api_key.*required"),
        ([SETTINGS], {"settings": "not_an_object"}, "Expected an object"),
        ([variable("ids", "array", required=False, items={"type": "integer"})], {"ids": "nope"}, "Expected an array"),
    ],
    ids=[
        "not-an-object", "missing-required", "agent-input-set-by-user", "uncastable",
        "nested-missing-required", "nested-wrong-type", "array-wrong-type",
    ],
)
def test_an_invalid_configuration_is_rejected(variables, configuration, message):
    with pytest.raises(PythonCodeToolConfigSerializerError, match=message):
        validate(variables, configuration)
