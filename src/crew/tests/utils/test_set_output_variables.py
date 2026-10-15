import string
import time

from dotdict import DotDict

from utils.set_output_variables import set_output_variables


def _make_state(variables: DotDict) -> dict:
    return {
        "state_history": [],
        "variables": variables,
        "system_variables": None,
        "execution_counts": {},
    }


def _deep_path_segments(count: int) -> list[str]:
    # Deterministic, unique segment names: a, b, c, ..., z, aa, ab, ...
    segments = []
    letters = string.ascii_lowercase
    index = 0
    while len(segments) < count:
        first = letters[(index // len(letters)) % len(letters)]
        second = letters[index % len(letters)]
        segments.append(f"{first}{second}")
        index += 1
    return segments


def test_set_output_variables_with_shallow_path_still_works():
    state = _make_state(DotDict())

    set_output_variables(state, "variables.result", "hello")

    assert state["variables"].result == "hello"


def test_set_output_variables_with_deeply_nested_path_completes_quickly_and_is_correct():
    segments = _deep_path_segments(30)
    output_variable_path = "variables." + ".".join(segments)

    state = _make_state(DotDict())

    start = time.perf_counter()
    set_output_variables(state, output_variable_path, "deep_value")
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"set_output_variables took too long for a deep path: {elapsed:.3f}s"

    value = state["variables"]
    for segment in segments:
        value = getattr(value, segment)
    assert value == "deep_value"


def test_set_output_variables_with_deeply_nested_path_merges_dict_output():
    segments = _deep_path_segments(28)
    output_variable_path = "variables." + ".".join(segments)

    state = _make_state(DotDict())
    set_output_variables(state, output_variable_path, {"first": 1})
    set_output_variables(state, output_variable_path, {"second": 2})

    value = state["variables"]
    for segment in segments:
        value = getattr(value, segment)

    assert value.first == 1
    assert value.second == 2
