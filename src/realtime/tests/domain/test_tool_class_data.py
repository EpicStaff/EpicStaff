import pytest
from pydantic import ValidationError

from domain.models.realtime_tool import ToolClassData


def test_valid_payload_parses():
    payload = {
        "description": "A tool that searches the web",
        "args_schema": {
            "title": "SearchInput",
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }

    data = ToolClassData.model_validate(payload)

    assert data.description == "A tool that searches the web"
    assert data.args_schema.properties == {"query": {"type": "string"}}
    assert data.args_schema.required == ["query"]


def test_missing_args_schema_defaults_to_empty():
    data = ToolClassData.model_validate({"description": "No schema tool"})

    assert data.args_schema.properties == {}
    assert data.args_schema.required == []


def test_missing_description_raises_validation_error():
    with pytest.raises(ValidationError):
        ToolClassData.model_validate({"args_schema": {"properties": {}}})


def test_wrong_type_for_properties_raises_validation_error():
    payload = {
        "description": "Malicious tool",
        "args_schema": {"properties": "not-a-dict", "required": []},
    }

    with pytest.raises(ValidationError):
        ToolClassData.model_validate(payload)


def test_wrong_type_for_description_raises_validation_error():
    payload = {"description": {"__reduce__": "malicious"}, "args_schema": {}}

    with pytest.raises(ValidationError):
        ToolClassData.model_validate(payload)
