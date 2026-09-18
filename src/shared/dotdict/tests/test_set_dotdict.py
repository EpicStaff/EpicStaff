import pytest

from dotdict import DotDict, DotList


def test_missing_attribute_raises_instead_of_autocreating():
    """DotDict does not auto-vivify nested attributes on access (removed
    deliberately, see commit bafb0ab79 "undo dotdict changes"). Deep
    structures must be assigned explicitly."""
    variables = DotDict({})
    with pytest.raises(AttributeError):
        variables.a.b.c.d = 1

    variables.a = {"b": {"c": {"d": 1}}}
    assert isinstance(variables.a, DotDict)
    assert isinstance(variables.a.b, DotDict)
    assert isinstance(variables.a.b.c, DotDict)
    assert variables.a.b.c.d == 1


def test_model_dump_nested_dotdict():
    variables = DotDict({"a": {"b": {"c": {"d": 1}}}})
    dumped = variables.model_dump()
    assert dumped == {"a": {"b": {"c": {"d": 1}}}}


def test_update_method():
    variables = DotDict({"x": 5})
    variables.update({"y": 10})
    assert variables.x == 5
    assert variables.y == 10


def test_dotlist_conversion():
    data = [1, {"a": 2}]
    dotlist = DotList(data)
    assert isinstance(dotlist[0], int)
    assert isinstance(dotlist[1], DotDict)
    assert dotlist[1].a == 2


def test_nested_dotlist_and_dotdict():
    # Deliberately not named "items": DotDict subclasses dict, and dot-access
    # only falls through to __getattr__ when normal attribute lookup fails —
    # a key named "items" (or "keys", "values", "update", ...) would resolve
    # to the inherited dict method instead of the stored value.
    variables = DotDict({})
    variables.records = []

    assert isinstance(variables.records, DotList)
    variables.records.append({"id": 1})
    variables.records.append({"id": 2, "nested": {"value": 5}})

    assert isinstance(variables.records, DotList)
    assert isinstance(variables.records[0], DotDict)
    assert variables.records[0].id == 1
    assert variables.records[1].nested.value == 5


def test_accessing_nonexistent_attribute_raises_attribute_error():
    variables = DotDict({})
    with pytest.raises(AttributeError):
        _ = variables.new_attr

    variables.new_attr = DotDict()
    variables.new_attr.sub = 123
    assert variables.new_attr.sub == 123


def test_setitem_with_dotobject():
    variables = DotDict({})
    variables["x"] = {"y": {"z": 99}}
    assert isinstance(variables.x, DotDict)
    assert variables.x.y.z == 99


def test_dotlist_append_autoconversion():
    dotlist = DotList([])
    dotlist.append({"foo": "bar"})
    assert isinstance(dotlist[0], DotDict)
    assert dotlist[0].foo == "bar"


def test_model_dump_dotlist():
    dotlist = DotList([{"a": 1}, {"b": 2}])
    dumped = dotlist.model_dump()
    assert dumped == [{"a": 1}, {"b": 2}]
