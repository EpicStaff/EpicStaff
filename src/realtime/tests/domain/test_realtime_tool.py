import pytest

from domain.models.realtime_tool import RealtimeTool, ToolParameters


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("", ""),
        ("short description", "short description"),
        ("a" * 1024, "a" * 1024),
        # Providers reject tool descriptions over 1024 characters.
        ("b" * 1025, "b" * 1021 + "..."),
        ("x" * 5000, "x" * 1021 + "..."),
    ],
    ids=["empty", "short", "exactly-1024", "1025", "5000"],
)
def test_description_is_cut_to_the_providers_limit(description, expected):
    tool = RealtimeTool(name="t", parameters=ToolParameters(properties={}))

    tool.description = description

    assert tool.description == expected
