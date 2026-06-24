import pytest
from pydantic_core import PydanticUndefined

from services.crew.tool_factories.args_schema_factory import ArgsSchemaFactory
from src.shared.models import VariableType
from tests.services.tool_factories.helpers import make_var


@pytest.mark.parametrize(
    "input_type,expected_in_schema",
    [
        ("user_input", False),
        ("agent_input", True),
        ("mixed", True),
    ],
)
def test_variable_inclusion_by_input_type(input_type, expected_in_schema):
    var = make_var(name="field", input_type=input_type)
    model = ArgsSchemaFactory.create("tool", [var])
    assert ("field" in model.model_fields) is expected_in_schema


@pytest.mark.parametrize("input_type", ["agent_input", "mixed"])
def test_variable_in_resolved_variables_is_excluded(input_type):
    var = make_var(name="field", input_type=input_type)
    model = ArgsSchemaFactory.create("tool", [var], resolved_variables={"field"})
    assert "field" not in model.model_fields


@pytest.mark.parametrize(
    "required,expected_required,expected_default",
    [
        (True, True, PydanticUndefined),
        (False, False, None),
    ],
)
def test_setting_default_for_field_if_variable_has_no_default_value(
    required,
    expected_required,
    expected_default,
):
    var = make_var(name="field", required=required, default_value=None)
    model = ArgsSchemaFactory.create("tool", [var])
    field_info = model.model_fields["field"]
    assert field_info.is_required() is expected_required
    assert field_info.default is expected_default


@pytest.mark.parametrize(
    "type_name,default_value,expected",
    [
        (VariableType.STRING, "value", "value"),
        (VariableType.STRING, "", ""),
        (VariableType.NUMBER, "43", 43),
        (VariableType.NUMBER, 0, 0),
        (VariableType.NUMBER, "4.3", 4.3),
        (VariableType.NUMBER, 0.1, 0.1),
        (VariableType.BOOLEAN, False, False),
    ],
)
def test_field_with_default_value_as_simple_type(default_value, type_name, expected):
    var = make_var(name="field", type=type_name, default_value=default_value)
    model = ArgsSchemaFactory.create("tool", [var])
    field_info = model.model_fields["field"]
    assert field_info.default == expected


@pytest.mark.parametrize(
    "type_name,default_value",
    [
        (VariableType.STRING, "value"),
        (VariableType.STRING, ""),
        (VariableType.NUMBER, "43"),
        (VariableType.NUMBER, 0),
        (VariableType.NUMBER, "4.3"),
        (VariableType.NUMBER, 0.1),
        (VariableType.BOOLEAN, False),
    ],
)
@pytest.mark.parametrize(
    "description,expected_description",
    [
        (None, "Use `{default_value}` as the default value."),
        ("", "Use `{default_value}` as the default value."),
        (
            "Given description.",
            (
                "Given description. If you cannot determine an appropriate value, "
                "from the given context, use `{default_value}` as the default."
            ),
        ),
    ],
)
def test_default_value_appended_to_description(
    type_name,
    default_value,
    description,
    expected_description,
):
    expected_description = expected_description.format(default_value=default_value)
    var = make_var(
        name="field",
        type=type_name,
        default_value=default_value,
        description=description,
    )
    model = ArgsSchemaFactory.create("tool", [var])
    field_info = model.model_fields["field"]
    assert field_info.description == expected_description


def test_empty_variables_creates_model_with_no_fields():
    model = ArgsSchemaFactory.create("tool", [])
    assert model.model_fields == {}


@pytest.mark.parametrize(
    "model_name,expected_model_name",
    [
        ("alert tool", "ArgsSchemaOfAlertTool"),
        ("alert-tool", "ArgsSchemaOfAlertTool"),
        ("alert_tool", "ArgsSchemaOfAlertTool"),
        ("ALERT TOOL", "ArgsSchemaOfAlertTool"),
    ],
)
def test_normalizes_model_name(model_name, expected_model_name):
    model = ArgsSchemaFactory.create(model_name, [])
    assert model.__name__ == expected_model_name
