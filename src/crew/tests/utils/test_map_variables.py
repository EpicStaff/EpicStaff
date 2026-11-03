import re
import string
import time

import pytest
from dotdict import DotDict

from services.graph.exceptions import InvalidStatePathError
from utils.map_variables import map_variables_to_input


def _deep_path_segments(count: int) -> list[str]:
    segments = []
    letters = string.ascii_lowercase
    index = 0
    while len(segments) < count:
        first = letters[(index // len(letters)) % len(letters)]
        second = letters[index % len(letters)]
        segments.append(f"{first}{second}")
        index += 1
    return segments


def _build_nested_dotdict(segments: list[str], leaf_value):
    nested: object = leaf_value
    for segment in reversed(segments):
        nested = {segment: nested}
    return DotDict(nested)


def test_map_variables_to_input_with_deeply_nested_path_completes_quickly_and_is_correct():
    segments = _deep_path_segments(30)
    variables = _build_nested_dotdict(segments, "deep_value")
    input_key = "variables." + ".".join(segments)

    start = time.perf_counter()
    mapped = map_variables_to_input(variables, {"output_key": input_key})
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"map_variables_to_input took too long for a deep path: {elapsed:.3f}s"
    assert mapped == {"output_key": "deep_value"}


def test_map_variables_to_input_with_deeply_nested_missing_path_uses_default():
    segments = _deep_path_segments(28)
    # Build every level except the final one, so traversal walks the full
    # depth before falling through to the default value on the last key.
    variables = _build_nested_dotdict(segments[:-1], "unreachable_leaf")
    input_key = "variables." + ".".join(segments) + "|fallback"

    start = time.perf_counter()
    mapped = map_variables_to_input(variables, {"output_key": input_key})
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, (
        f"map_variables_to_input took too long for a missing deep path: {elapsed:.3f}s"
    )
    assert mapped == {"output_key": "fallback"}


@pytest.mark.parametrize(
    ("input_key", "rejected_path"),
    [
        ("variables.__class__.__init__.__globals__", "variables.__class__.__init__.__globals__"),
        ("variables._properties", "variables._properties"),
        ("variables.orders[0].__dict__", "variables.orders[0].__dict__"),
        # A default does not turn the rejection into a silent fallback.
        ("variables.user._secret|fallback", "variables.user._secret"),
    ],
)
def test_map_variables_to_input_rejects_path_segment_starting_with_underscore(
    input_key, rejected_path
):
    variables = DotDict({"user": {"name": "Ann"}, "orders": [{"id": 1}]})

    with pytest.raises(InvalidStatePathError, match=re.escape(f"'{rejected_path}'")):
        map_variables_to_input(variables, {"output_key": input_key})


def test_map_variables_to_input_reads_segment_with_underscore_inside_its_name():
    variables = DotDict({"user_profile": {"first_name": "Ann"}})

    mapped = map_variables_to_input(variables, {"name": "variables.user_profile.first_name"})

    assert mapped == {"name": "Ann"}
