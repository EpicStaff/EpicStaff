"""Round-trip test for the args_schema <-> variables shared conversion helpers.

Placed in crew's test suite (rather than django_app's) since crew imports
`src.shared.models` the same way and this branch's task must not touch
src/django_app.
"""

from src.shared.models import args_schema_to_variables, variables_to_args_schema


def test_variables_to_args_schema_round_trips_through_args_schema_to_variables():
    original_args_schema = {
        "properties": {
            "topic": {"type": "string", "description": "Topic to research"},
            "max_results": {"type": "integer", "description": "Result cap"},
            "filters": {
                "type": "object",
                "description": "Nested filters",
                "properties": {
                    "category": {"type": "string", "description": "Category name"}
                },
                "required": ["category"],
            },
        },
        "required": ["topic"],
    }

    variables = args_schema_to_variables(original_args_schema)
    rebuilt_args_schema = variables_to_args_schema(variables)

    assert rebuilt_args_schema["required"] == ["topic"]

    properties = rebuilt_args_schema["properties"]
    assert properties["topic"]["type"] == "string"
    assert properties["topic"]["description"] == "Topic to research"
    assert properties["max_results"]["type"] == "number"
    assert properties["filters"]["type"] == "object"
    assert properties["filters"]["required"] == ["category"]
    assert properties["filters"]["properties"]["category"]["type"] == "string"
