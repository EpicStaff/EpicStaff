import pytest

from foundation.utils.lazy import LazyImport


def test_wraps_whole_module_when_object_omitted():
    lazy_json = LazyImport("json")
    assert lazy_json.dumps({"a": 1}) == '{"a": 1}'


def test_wraps_single_object_from_module():
    lazy_dumps = LazyImport("json", "dumps")
    assert lazy_dumps({"a": 1}) == '{"a": 1}'


def test_call_forwards_args_and_kwargs():
    lazy_dict = LazyImport("builtins", "dict")
    assert lazy_dict(a=1, b=2) == {"a": 1, "b": 2}


def test_getattr_resolves_an_attribute_of_the_wrapped_object():
    import math

    lazy_math = LazyImport("math")
    assert lazy_math.pi == math.pi


def test_import_is_deferred_until_first_access():
    lazy = LazyImport("this_module_does_not_exist_anywhere")
    with pytest.raises(ModuleNotFoundError):
        lazy.lazy_value


def test_lazy_value_is_cached_after_first_resolution():
    lazy = LazyImport("json", "dumps")
    assert lazy.lazy_value is lazy.lazy_value


def test_bare_reference_cannot_be_used_in_an_except_clause():
    """Documented limitation: LOAD_GLOBAL/LOAD_FAST never calls __getattr__/__call__,
    so a bare name bound to a LazyImport instance can't stand in for the real class."""
    lazy_value_error = LazyImport("builtins", "ValueError")
    with pytest.raises(TypeError, match="catching classes"):
        try:
            raise ValueError("boom")
        except lazy_value_error:
            pass
