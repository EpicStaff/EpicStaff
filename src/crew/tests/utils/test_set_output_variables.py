import re
import string
import time

import pytest

from dotdict import DotDict, DotList

from services.graph.exceptions import InvalidStatePathError
from utils.set_output_variables import set_output_variables


@pytest.fixture(autouse=True)
def shared_dotdict_classes_stay_unchanged():
    """Fail a test that changes DotDict or DotList, and undo the change.

    Both classes are shared by every session in the crew process. Restoring them keeps one
    regressed guard from breaking every later test in the run.
    """
    snapshots = {cls: dict(vars(cls)) for cls in (DotDict, DotList)}
    yield
    changed = []
    for cls, before in snapshots.items():
        after = dict(vars(cls))
        for name in after.keys() - before.keys():
            delattr(cls, name)
            changed.append(f"{cls.__name__}.{name} added")
        for name, original in before.items():
            if name not in after or after[name] is not original:
                setattr(cls, name, original)
                changed.append(f"{cls.__name__}.{name} changed")
    if changed:
        pytest.fail(f"Test changed shared classes: {', '.join(changed)}")


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


@pytest.mark.parametrize(
    "output_variable_path",
    [
        "variables.__class__.status",
        "variables.__class__.__init__",
        "variables._properties.x",
        "variables.user._secret",
        "variables.orders[0].__dict__",
        "variables._x",
    ],
)
def test_set_output_variables_rejects_path_segment_starting_with_underscore(output_variable_path):
    state = _make_state(DotDict({"user": {"name": "Ann"}, "orders": [{"id": 1}]}))

    with pytest.raises(InvalidStatePathError, match=re.escape(output_variable_path)):
        set_output_variables(state, output_variable_path, "attacker_value")

    assert state["variables"].deep_dump() == {"user": {"name": "Ann"}, "orders": [{"id": 1}]}


def test_set_output_variables_allows_underscore_inside_segment_name():
    state = _make_state(DotDict())

    set_output_variables(state, "variables.user_profile.first_name", "Ann")
    set_output_variables(state, "variables.user_profile", {"last_name": "Lee"})

    assert state["variables"].deep_dump() == {
        "user_profile": {"first_name": "Ann", "last_name": "Lee"}
    }


@pytest.mark.parametrize("internal_key", ["_properties", "_setters", "__dict__", "__class__"])
def test_set_output_variables_whole_variables_merge_stores_underscore_keys_as_data(internal_key):
    state = _make_state(DotDict({"counter": 1}))

    set_output_variables(state, "variables", {internal_key: {"status": "x"}, "other": 2})
    set_output_variables(state, "variables", {"counter": 3})

    variables = state["variables"]
    assert variables[internal_key] == {"status": "x"}
    assert variables.counter == 3
    assert variables.other == 2


def test_set_output_variables_whole_variables_merge_still_deep_merges_dicts():
    state = _make_state(DotDict({"message_history": {"chat_a": [1]}}))

    set_output_variables(state, "variables", {"message_history": {"chat_b": [2]}, "_id": "abc"})

    assert state["variables"].deep_dump() == {
        "message_history": {"chat_a": [1], "chat_b": [2]},
        "_id": "abc",
    }


def test_set_output_variables_whole_variables_merge_deep_merges_key_named_like_a_dict_method():
    state = _make_state(DotDict({"items": {"b": 2}}))

    set_output_variables(state, "variables", {"items": {"a": 1}})

    assert state["variables"].deep_dump() == {"items": {"a": 1, "b": 2}}
