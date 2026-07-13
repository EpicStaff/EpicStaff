import pytest

from tables.services.persistent_variables_service import (
    PersistentVariablesService,
    _MISSING,
)

svc = PersistentVariablesService()


def test_get_by_path_missing_returns_sentinel():
    assert svc.get_by_path({"a": {"b": 1}}, "a.x") is _MISSING
    assert svc.get_by_path({}, "a") is _MISSING


def test_get_by_path_explicit_null_is_not_missing():
    # a value that is explicitly None must be distinguishable from "absent"
    assert svc.get_by_path({"context": None}, "context") is None


def test_get_by_path_nested_value():
    assert svc.get_by_path({"a": {"b": {"c": 5}}}, "a.b.c") == 5


def test_deep_merge_recurses_and_payload_wins():
    base = {"a": {"x": 1, "y": 2}, "k": "base"}
    updates = {"a": {"y": 99, "z": 3}, "k": "override"}
    assert svc.deep_merge(base, updates) == {
        "a": {"x": 1, "y": 99, "z": 3},
        "k": "override",
    }


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"x": 1}}
    svc.deep_merge(base, {"a": {"x": 2}})
    assert base == {"a": {"x": 1}}


def test_extract_org_paths_including_null_default():
    variables = {
        "variables": {"counter": 0, "context": None, "ignored": "no"},
        "persistent_variables": {"organization": ["counter", "context"], "user": []},
    }
    assert svc.extract(variables, "organization") == {"counter": 0, "context": None}


def test_extract_skips_genuinely_missing_path():
    variables = {
        "variables": {"counter": 0},
        "persistent_variables": {"organization": ["counter", "gone"], "user": []},
    }
    assert svc.extract(variables, "organization") == {"counter": 0}
