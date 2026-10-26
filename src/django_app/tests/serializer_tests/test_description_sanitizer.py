"""A user-authored tool description is stored without control characters, at most
1024 characters and trimmed, and one left without visible text is rejected: an
empty stored description would fail the next import of the tool."""

import pytest
from rest_framework import serializers

from tables.serializers.utils.description_sanitizer import validate_tool_description


@pytest.mark.parametrize(
    ("description", "stored"),
    [
        ("Reads a file.", "Reads a file."),
        ("\x07abc", "abc"),
        ("\x07 abc \x1b", "abc"),
        ("a" * 1023 + " more", "a" * 1023),
        ("b" * 1025, "b" * 1024),
    ],
    ids=["clean", "control-character", "space-left-at-the-edges", "space-at-the-cap", "over-the-cap"],
)
def test_description_is_stored_cleaned(description, stored):
    assert validate_tool_description(description) == stored


@pytest.mark.parametrize(
    "description",
    ["\x1b\x07", "\x07 \x07"],
    ids=["control-characters-only", "control-characters-around-a-space"],
)
def test_description_without_visible_text_is_rejected(description):
    with pytest.raises(serializers.ValidationError, match="Description must contain visible text."):
        validate_tool_description(description)
