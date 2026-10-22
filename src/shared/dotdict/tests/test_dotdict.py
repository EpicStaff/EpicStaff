import json
from types import MappingProxyType

import pytest
from pydantic import BaseModel

from dotdict import DotDict, DotList, DotObject


def test_nested_values_are_reachable_by_attribute_and_key():
    d = DotDict({"a": 1, "x": {"y": [{"z": 10}, {"a": 33}]}})

    assert (d.a, d.x.y[0].z, d.x.y[1].a) == (1, 10, 33)
    d.b = 123
    d["c"] = 456
    assert (d["b"], d.c) == (123, 456)
    assert len(DotDict()) == 0
    rows = DotList([{"x": 1}])
    rows[0] = {"y": 2}
    assert rows[0].y == 2
    with pytest.raises(AttributeError):
        _ = d.missing


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2}}),
        ({"a": {"b": {"c": [1, 2, {"d": 3}]}}}, {"a": {"b": {"c": [1, 2, {"d": 3}]}}}),
        (("a", {"c": 2, "e": [1, 2, ("3", 4)]}), ["a", {"c": 2, "e": [1, 2, ["3", 4]]}]),
        (["a", {"c": 2, "e": [1, 2, ("3", 4)]}], ["a", {"c": 2, "e": [1, 2, ["3", 4]]}]),
        ([1, {"x": 2}, [3, {"y": 4}]], [1, {"x": 2}, [3, {"y": 4}]]),
        (123, 123),
    ],
    ids=["dict", "deep", "tuple", "list", "mixed-list", "scalar"],
)
def test_dump_and_json_give_plain_python_data(value, expected):
    wrapped = DotObject(value)

    assert json.loads(json.dumps(wrapped)) == expected
    if isinstance(wrapped, (DotDict, DotList)):
        assert wrapped.model_dump() == expected
    else:
        assert wrapped == expected


def test_sets_serialize_as_lists():
    loaded = json.loads(json.dumps(DotObject({"a": {"b": [1, {"c": 2}]}, "set": {4, 5, 6}})))

    assert loaded["a"]["b"][1]["c"] == 2
    assert sorted(loaded["set"]) == [4, 5, 6]


class _WithDotDict(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    args: DotDict = None


class _WithDotList(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    items: DotList = None


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # An unset Optional field keeps its None default unvalidated (as in the
        # dynamically built tool args_schema); serializing it must not crash.
        (_WithDotDict(), {"args": None}),
        (_WithDotList(), {"items": None}),
        (_WithDotDict(args=DotDict({"a": 1, "b": {"c": 2}})), {"args": {"a": 1, "b": {"c": 2}}}),
        (_WithDotList(items=DotList([1, {"x": 2}, [3, {"y": 4}]])), {"items": [1, {"x": 2}, [3, {"y": 4}]]}),
    ],
    ids=["unset-dotdict", "unset-dotlist", "dotdict", "dotlist"],
)
def test_pydantic_fields_serialize(model, expected):
    assert model.model_dump() == expected


@pytest.mark.parametrize(
    "existing",
    [DotDict({"c": 1}), DotList([1, 2, 3])],
    ids=["dotdict", "dotlist"],
)
def test_an_already_built_container_is_reused_not_copied_on_construction(existing):
    """Construction is the hot path; wrapping must not copy what is already wrapped."""
    outer = DotDict({"nested": existing})

    assert DotObject(existing) is existing
    assert outer.nested is existing
    assert DotList([existing])[0] is existing


ASSIGNMENTS = {
    "attribute": lambda target, value: setattr(target, "nested", value),
    "key": lambda target, value: target.__setitem__("nested", value),
    "update": lambda target, value: target.update({"nested": value}),
    "list-append": lambda target, value: target.rows.append(value),
    "list-insert": lambda target, value: target.rows.insert(0, value),
    "list-extend": lambda target, value: target.rows.extend([value]),
    "list-setitem": lambda target, value: target.rows.__setitem__(0, value),
}


def _assigned(target, operation):
    if operation in ("list-append", "list-extend"):
        return target.rows[-1]
    return target.rows[0] if operation.startswith("list") else target.nested


@pytest.mark.parametrize("operation", list(ASSIGNMENTS))
@pytest.mark.parametrize(
    "source",
    [lambda: DotDict({"value": 0}), lambda: DotList([DotDict({"value": 0})])],
    ids=["dotdict", "dotlist"],
)
def test_assigning_a_container_copies_it(operation, source):
    """Flow nodes assign one variable from another; a later change to either must
    not show up in the other (and a row appended in a loop must not alias)."""
    value = source()
    target = DotDict({"rows": [None]})

    ASSIGNMENTS[operation](target, value)
    assigned = _assigned(target, operation)
    (value if isinstance(value, DotDict) else value[0]).value = 1

    assert assigned is not value
    assert (assigned if isinstance(assigned, DotDict) else assigned[0]).value == 0


def test_a_deeply_nested_assignment_is_copied_all_the_way_down():
    variables = DotDict({"b": {"k": 0, "nested": {"deep": 0}}})
    variables.a = variables.b
    variables.a.k = 1
    variables.a.nested.deep = 1

    assert variables.b.deep_dump() == {"k": 0, "nested": {"deep": 0}}


def test_assigning_a_variable_into_itself_makes_a_snapshot_not_a_cycle():
    variables = DotDict({"a": 1, "b": {"c": 2}})
    variables.snapshot = variables

    assert variables.snapshot is not variables
    assert "snapshot" not in variables.snapshot
    assert variables.deep_dump()["snapshot"] == {"a": 1, "b": {"c": 2}}
    assert json.loads(json.dumps(variables))["snapshot"]["b"]["c"] == 2


def test_assigning_a_variable_inside_a_plain_container_into_itself_is_not_a_cycle():
    variables = DotDict({"a": 1})
    variables.history = [{"state": variables}]

    assert variables.history[0].state is not variables
    assert json.loads(json.dumps(variables))["history"][0]["state"] == {"a": 1}


def test_assigning_a_plain_object_keeps_its_identity():
    sentinel = object()
    d = DotDict()
    d.obj = sentinel
    d.wrapper = {"inner": sentinel}

    assert d.obj is sentinel
    assert d.wrapper.inner is sentinel


@pytest.mark.parametrize(
    ("wrap_in_plain_container", "unwrap"),
    [
        (lambda variable: {"inner": variable}, lambda assigned: assigned.inner),
        (lambda variable: [variable], lambda assigned: assigned[0]),
        (lambda variable: (variable,), lambda assigned: assigned[0]),
    ],
    ids=["dict", "list", "tuple"],
)
def test_assigning_a_plain_container_holding_a_variable_copies_the_variable(
    wrap_in_plain_container, unwrap
):
    variables = DotDict({"other": {"value": 0}})
    variables["snapshot"] = wrap_in_plain_container(variables.other)
    snapshot_of_other = unwrap(variables.snapshot)

    variables.other.value = 1
    snapshot_of_other.extra = 2

    assert snapshot_of_other is not variables.other
    assert snapshot_of_other.deep_dump() == {"value": 0, "extra": 2}
    assert variables.other.deep_dump() == {"value": 1}


def _stored_by_construction(value):
    return DotDict({"nested": value}).nested


def _stored_by_key_assignment(value):
    variables = DotDict()
    variables["nested"] = value
    return variables.nested


def _stored_by_list_append(value):
    rows = DotList()
    rows.append(value)
    return rows[0]


STORE_PATHS = pytest.mark.parametrize(
    "store",
    [_stored_by_construction, _stored_by_key_assignment, _stored_by_list_append],
    ids=["construction", "key-assignment", "list-append"],
)


@STORE_PATHS
def test_tuples_and_sets_become_dot_lists_and_keep_their_leaf_values(store):
    leaf = object()

    from_tuple = store((leaf, {"a": 1}))
    from_set = store({"only"})

    assert isinstance(from_tuple, DotList)
    assert from_tuple[0] is leaf
    assert from_tuple[1].a == 1
    assert isinstance(from_set, DotList)
    assert list(from_set) == ["only"]


class _PlainDictSubclass(dict):
    pass


@pytest.mark.parametrize(
    "mapping",
    [_PlainDictSubclass({"a": {"b": 1}}), MappingProxyType({"a": {"b": 1}})],
    ids=["dict-subclass", "read-only-mapping"],
)
@STORE_PATHS
def test_other_mapping_types_are_wrapped_like_dicts(store, mapping):
    wrapped = store(mapping)

    assert isinstance(wrapped, DotDict)
    assert wrapped.a.b == 1


@pytest.mark.parametrize("reserved_key", ["__properties__", "__setters__"])
@STORE_PATHS
def test_reserved_keys_of_a_nested_plain_dict_are_consumed_not_stored(store, reserved_key):
    """Crew compiles these keys (the chat API rejects them for that reason), so a nested
    dict carrying one must keep being treated as a definition, not as data."""
    assert dict(store({reserved_key: {}, "kept": 1})) == {"kept": 1}
    with pytest.raises(ValueError, match="Invalid expression"):
        store({"deeper": {reserved_key: {"name": "1 +"}}})
