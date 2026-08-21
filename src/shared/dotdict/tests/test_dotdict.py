import json
import pytest

from dotdict import DotDict, DotList, DotObject


def test_dotdict_initialization():
    data = {"a": 1, "b": {"c": 2}}
    dotdict = DotDict(data)
    assert dotdict.a == 1
    assert dotdict.b.c == 2


def test_dotdict_nested_access():
    data = {"x": {"y": {"z": 10}}}
    dotdict = DotDict(data)
    assert dotdict.x.y.z == 10


def test_dotdict_nested_list_access():
    data = {"x": {"y": [{"z": 10}, {"a": 33}]}}
    dotdict = DotDict(data)
    assert dotdict.x.y[0].z == 10


# def test_dotdict_property():
#     data = {"a": 2}
#     dotdict = DotDict(data)
#     dotdict.add_property("double_a", "a * 2")
#     assert dotdict.double_a == 4


# def test_dotdict_setter():
#     data = {"a": 10}
#     dotdict = DotDict(data)
#     dotdict.add_setter("a", "value * 2")
#     dotdict.a = 5
#     assert dotdict.a == 10  # Because the setter doubles the value


# def test_dotdict_update():
#     dotdict = DotDict({"a": 1})
#     dotdict.update({"b": 2})
#     assert dotdict.b == 2


def test_dotdict_json_dumps():
    import json

    data = {"a": 1, "b": {"c": 2}}
    dotdict = DotDict(data)
    dumped = json.dumps(dotdict)
    assert dumped == '{"a": 1, "b": {"c": 2}}'


def test_dotdict_model_dump():
    data = {"a": 1, "b": {"c": 2}}
    dotdict = DotDict(data)
    dumped = dotdict.model_dump()
    assert dumped == data


def test_dotobj_model_dump_tuple():
    data = ("a", {"c": 2, "e": [1, 2, ("3", 4)]})
    dotobject = DotObject(data)
    dumped = dotobject.model_dump()

    expected_data = ["a", {"c": 2, "e": [1, 2, ["3", 4]]}]
    assert dumped == expected_data


def test_dotobj_json_dump_tuple():
    data = ("a", {"c": 2, "e": [1, 2, ("3", 4)]})
    dotobject = DotObject(data)
    json_dumped_and_loaded = json.loads(json.dumps(dotobject))
    expected_data = ["a", {"c": 2, "e": [1, 2, ["3", 4]]}]
    assert json_dumped_and_loaded == expected_data


def test_dotobj_model_dump_list():
    data = ["a", {"c": 2, "e": [1, 2, ("3", 4)]}]
    dotobject = DotObject(data)
    dumped = dotobject.model_dump()

    expected_data = ["a", {"c": 2, "e": [1, 2, ["3", 4]]}]
    assert dumped == expected_data

    expected_data = [1, 2, "3", test_obj]
    assert len(expected_data) == len(dumped)
    assert isinstance(dumped, list)
    for val in expected_data:
        assert val in dumped


def test_dotobj_json_dump_set():
    data = {1, 2, "3"}
    dotobject = DotObject(data)
    json_dumped_and_loaded = json.loads(json.dumps(dotobject))

    expected_data = [1, 2, "3"]
    assert len(expected_data) == len(dotobject)
    assert isinstance(json_dumped_and_loaded, list)
    for val in expected_data:
        assert val in json_dumped_and_loaded


def test_dotdict_empty_init():
    d = DotDict()
    assert isinstance(d, DotDict)
    assert len(d) == 0


# def test_dotdict_init_with_properties_and_setters():
#     d = DotDict({
#         "a": 2,
#         "__properties__": {"double": "a * 2"},
#         "__setters__": {"a": "value + 10"}
#     })
#     assert d.double == 4
#     d.a = 5
#     # setter modifies before assignment, then property updates
#     assert d.a == 15
#     assert d.double == 30


# def test_dotdict_setitem_triggers_property_update():
#     d = DotDict({"a": 1})
#     d.add_property("b", "a + 5")
#     assert d.b == 6
#     d.a = 10
#     assert d.b == 15  # property updated automatically


# def test_dotdict_nested_property_with_other_dotdicts():
#     d = DotDict({"x": {"y": 2}})
#     d.add_property("sum_y", "x.y + 3")
#     assert d.sum_y == 5


# def test_dotdict_add_property_invalid_expression():
#     d = DotDict({"a": 1})
#     with pytest.raises(ValueError):
#         d.add_property("b", "a +")  # invalid syntax


# def test_dotdict_add_setter_invalid_expression():
#     d = DotDict()
#     with pytest.raises(ValueError):
#         d.add_setter("a", "value +")  # invalid syntax


def test_dotdict_attr_error_on_missing():
    d = DotDict({"x": 1})
    with pytest.raises(AttributeError):
        _ = d.y


def test_dotdict_set_attr_and_dict_consistency():
    d = DotDict()
    d.a = 123
    assert d["a"] == 123
    d["b"] = 456
    assert d.b == 456


# def test_dotdict_update_with_kwargs():
#     d = DotDict({"x": 1})
#     d.update(y=2, z=3)
#     assert d.y == 2 and d.z == 3


# def test_dotdict_nested_mutation_propagates():
#     d = DotDict({"a": {"b": {"c": 5}}})
#     d.a.b.c = 10
#     assert d.a.b.c == 10


# def test_dotlist_append_extend_insert_and_model_dump():
#     l = DotList()
#     l.append({"x": 1})
#     assert isinstance(l[0], DotDict)
#     l.extend([{"y": 2}, {"z": 3}])
#     assert l[1].y == 2
#     l.insert(0, {"a": 0})
#     assert l[0].a == 0
#     dumped = l.model_dump()
#     assert dumped == [{"a": 0}, {"x": 1}, {"y": 2}, {"z": 3}]


def test_dotlist_setitem_replaces_with_dotobject():
    l = DotList([{"x": 1}])
    l[0] = {"y": 2}
    assert isinstance(l[0], DotDict)
    assert l[0].y == 2


def test_dotobject_non_iterable_pass_through():
    obj = DotObject(123)
    assert obj == 123


def test_dotdict_property_expression_reflects_latest_value():
    d = DotDict({"a": 2, "b": 3})
    d.add_property("sum", "a + b")
    assert d.sum == 5
    d.a = 5
    assert d.sum == 8


def test_dotdict_json_roundtrip_complex():
    import json

    data = {"a": {"b": [1, {"c": 2}]}, "nums": (1, 2, 3), "set": {4, 5, 6}}
    d = DotObject(data)
    dumped = json.dumps(d)
    loaded = json.loads(dumped)
    assert isinstance(loaded, dict)
    assert loaded["a"]["b"][1]["c"] == 2
    assert sorted(loaded["set"]) == [4, 5, 6]


def test_dotdict_model_dump_deep():
    d = DotObject({"a": {"b": {"c": [1, 2, {"d": 3}]}}})
    dumped = d.model_dump()
    assert dumped == {"a": {"b": {"c": [1, 2, {"d": 3}]}}}


def test_dotlist_model_dump_mixed_types():
    l = DotList([1, {"x": 2}, [3, {"y": 4}]])
    dumped = l.model_dump()
    assert dumped == [1, {"x": 2}, [3, {"y": 4}]]


def test_pydantic_serialize_none_dotdict_field_does_not_raise():
    """Regression test: bare Optional DotDict field with value None must
    serialize to None instead of crashing with AttributeError on
    `None.deep_dump()` (EST-3285 smoke test bug)."""
    from pydantic import BaseModel

    class Model(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        args: DotDict = None

    # Field left unset -> default (None) is used and, matching the real
    # dynamically-built tool args_schema scenario, is NOT re-validated
    # against dict_schema (validate_default defaults to False). This is
    # exactly the shape that previously crashed on serialization.
    m = Model()
    dumped = m.model_dump()
    assert dumped == {"args": None}


def test_pydantic_serialize_none_dotlist_field_does_not_raise():
    from pydantic import BaseModel

    class Model(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        items: DotList = None

    m = Model()
    dumped = m.model_dump()
    assert dumped == {"items": None}


def test_pydantic_serialize_non_none_dotdict_field_unchanged():
    """Ensure the None-guard does not alter existing deep_dump behavior
    for a real (non-None) DotDict value."""
    from pydantic import BaseModel

    class Model(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        args: DotDict = None

    m = Model(args=DotDict({"a": 1, "b": {"c": 2}}))
    dumped = m.model_dump()
    assert dumped == {"args": {"a": 1, "b": {"c": 2}}}


def test_pydantic_serialize_non_none_dotlist_field_unchanged():
    from pydantic import BaseModel

    class Model(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        items: DotList = None

    m = Model(items=DotList([1, {"x": 2}, [3, {"y": 4}]]))
    dumped = m.model_dump()
    assert dumped == {"items": [1, {"x": 2}, [3, {"y": 4}]]}
