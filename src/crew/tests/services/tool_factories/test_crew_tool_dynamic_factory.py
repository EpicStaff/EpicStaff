import pytest

from services.crew.tool_factories.crew_tool_dynamic_factory import (
    CrewToolDynamicFactory,
)
from src.shared.models import VariableType
from tests.services.tool_factories.helpers import make_var


def test_create_returns_tool_with_name_and_description():
    variables = [
        make_var(
            name="username",
            description="name of user.",
            default_value="rick",
        ),
        make_var(
            name="age",
            description="age of user.",
            type=VariableType.NUMBER,
            default_value=67,
        ),
    ]
    tool = CrewToolDynamicFactory.create(
        name="File manager tool",
        description="Help to manage files.",
        variables=variables,
        resolved_variables={"age"},
        func=lambda x: x,
    )
    assert tool.name == "File manager tool"
    assert tool.description == (
        "Tool Name: File manager tool\n"
        "Tool Arguments: {"
        "'username': {"
        "'description': 'name of user. If you cannot determine an appropriate value, "
        "from the given context, use `rick` as the default.', "
        "'type': 'str'"
        "}"
        "}\n"
        "Tool Description: Help to manage files."
    )


@pytest.mark.parametrize(
    "func_result",
    [
        1,
        0.2,
        "Garfield",
        {"username": "rick", "age": 70},
        [1, "agent-47", False],
    ],
)
def test_wrapped_func_return_original_result(func_result):
    expected_func_result = func_result
    tool = CrewToolDynamicFactory.create(
        name="Math Tool",
        description="Mathematics operations",
        variables=[],
        resolved_variables={},
        func=lambda x: x,
    )
    assert tool.func(func_result) == expected_func_result


def test_wrapped_func_return_error_as_str():
    def error_func(*args, **kwargs):
        raise ZeroDivisionError("division by zero")

    tool = CrewToolDynamicFactory.create(
        name="Math Tool",
        description="Mathematics operations",
        variables=[],
        resolved_variables={},
        func=error_func,
    )
    assert tool.func() == "ZeroDivisionError: division by zero"
