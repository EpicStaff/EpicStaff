import json

from utils import get_tool_data
from tests.fixtures import (
    test_tool_class_with_args_schema,
    test_tool_class_without_args_schema,
)


def test_get_tool_data_is_json_serializable(test_tool_class_with_args_schema):
    tool_data = get_tool_data(test_tool_class_with_args_schema())

    serialized = json.dumps(tool_data)

    assert json.loads(serialized) == tool_data


def test_get_tool_data_without_args_schema_is_json_serializable(
    test_tool_class_without_args_schema,
):
    tool_data = get_tool_data(test_tool_class_without_args_schema())

    serialized = json.dumps(tool_data)

    assert json.loads(serialized) == tool_data
