import pytest
from rest_framework.test import APIRequestFactory

from tables.exceptions import PythonCodeToolConfigSerializerError
from tables.serializers.model_serializers import (
    PythonCodeSerializer,
    PythonCodeToolConfigSerializer,
    PythonCodeToolSerializer,
)
from tables.models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization


def _org_request(org_id: int):
    """A minimal request whose active org is pre-resolved — lets a serializer
    unit test satisfy the org-scoped `tool` field without the full auth stack."""
    request = APIRequestFactory().post("/")
    request._rbac_active_org_id = org_id
    return request


@pytest.mark.django_db
def test_python_code_serializer_basic():
    code = PythonCode.objects.create(code="print('Hello')", libraries="requests numpy")
    serializer = PythonCodeSerializer(code)
    data = serializer.data
    assert "libraries" in data
    assert data["libraries"] == ["requests", "numpy"]


@pytest.mark.django_db
def test_python_code_serializer_to_internal_value():
    data = {"code": "print('ok')", "libraries": ["pandas", "pytest"]}
    serializer = PythonCodeSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    obj = serializer.save()
    assert obj.libraries == "pandas pytest"


@pytest.mark.django_db
def test_python_code_tool_serializer_create_and_update():
    code = PythonCode.objects.create(code="def main(): pass", libraries="requests")
    tool_data = {
        "name": "MyTool",
        "description": "test tool",
        "variables": [],
        "python_code": {
            "code": code.code,
            "entrypoint": code.entrypoint,
            "libraries": ["requests"],
            "global_kwargs": {},
        },
    }

    serializer = PythonCodeToolSerializer(data=tool_data)
    serializer.is_valid(raise_exception=True)
    tool = serializer.save()
    assert tool.python_code.code == "def main(): pass"

    update_data = {
        "description": "updated",
        "python_code": {"code": "def main(): return 1"},
    }
    serializer = PythonCodeToolSerializer(instance=tool, data=update_data, partial=True)
    serializer.is_valid(raise_exception=True)
    updated_tool = serializer.save()
    assert updated_tool.description == "updated"
    assert updated_tool.python_code.code == "def main(): return 1"


@pytest.mark.django_db
def test_python_code_tool_serializer_prevents_built_in_update():
    code = PythonCode.objects.create(code="print('ok')")
    tool = PythonCodeTool.objects.create(
        name="BuiltIn",
        description="desc",
        variables=[],
        python_code=code,
        built_in=True,
    )

    update_data = {
        "description": "update attempt",
        "python_code": {"code": "print('no')"},
    }
    serializer = PythonCodeToolSerializer(instance=tool, data=update_data, partial=True)
    with pytest.raises(Exception):
        serializer.is_valid(raise_exception=True)
        serializer.save()


@pytest.mark.django_db
def test_python_code_tool_config_serializer_validation():
    # The config's `tool` FK is org-scoped (hybrid): the serializer needs a request
    # in context and the tool must be visible to the active org.
    org = Organization.objects.create(name="Tool Cfg Org")
    context = {"request": _org_request(org.id)}

    code = PythonCode.objects.create(code="def main(): pass")
    tool = PythonCodeTool.objects.create(
        name="Tool1",
        description="desc",
        python_code=code,
        org=org,
        variables=[
            {
                "name": "arg1",
                "type": "string",
                "input_type": "user_input",
                "required": True,
            },
            {
                "name": "arg2",
                "type": "integer",
                "input_type": "user_input",
                "required": False,
            },
        ],
    )

    config_data = {
        "name": "config1",
        "tool": tool.pk,
        "configuration": {"arg1": "value1", "arg2": 10},
    }
    serializer = PythonCodeToolConfigSerializer(data=config_data, context=context)
    serializer.is_valid(raise_exception=True)
    obj = serializer.save(org=org)
    assert obj.name == "config1"
    assert obj.tool == tool

    invalid_data = {
        "name": "config2",
        "tool": tool.pk,
        "configuration": {"arg1": "val"},
    }
    invalid_data["configuration"]["arg2"] = "not_a_number"
    serializer = PythonCodeToolConfigSerializer(data=invalid_data)
    with pytest.raises(PythonCodeToolConfigSerializerError):
        serializer.is_valid(raise_exception=True)
