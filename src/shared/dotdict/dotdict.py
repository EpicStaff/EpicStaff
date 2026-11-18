import copy
from collections.abc import Mapping

# Every sandbox execution imports this module, so it stays off `ast`, `dataclasses`
# and `typing`: they were most of its import time.

# Refused on construction and never evaluated: run state carries user input.
_RESERVED_KEYS = ("__properties__", "__setters__")


class DotDict(dict):
    def __init__(self, dictionary=None):
        """Aliasing constructor: wraps `dictionary` without copying its contents.

        Already-wrapped DotDict/DotList values inside `dictionary` are aliased (not copied),
        so mutations on either the original or result affect both. Only safe at construction,
        where the caller cannot keep a reference. External assignments use __setitem__ (via
        `d[key] = value`), which copies via _copy_wrap.

        To get a detached copy, use deep_dump().
        """
        super().__init__()
        if dictionary is None:
            dictionary = {}
        dictionary = dict(dictionary)

        for reserved_key in _RESERVED_KEYS:
            if dictionary.pop(reserved_key, None):
                raise ValueError(f"DotDict does not support '{reserved_key}'.")

        super().update({key: _wrap(value) for key, value in dictionary.items()})

    def __setitem__(self, key, value):
        super().__setitem__(key, _copy_wrap(value))

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(f"'DotDict' object has no attribute '{key}'") from e

    def __setattr__(self, key, value):
        self[key] = value

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def model_dump(self):
        return dict(self)

    def deep_dump(self):
        """Recursively convert to plain dict — single-pass replacement for deepcopy(model_dump())."""
        result = {}
        for key, value in self.items():
            if isinstance(value, (DotDict, DotList)):
                result[key] = value.deep_dump()
            else:
                result[key] = copy.deepcopy(value)
        return result

    @classmethod
    def _validate(cls, value: object) -> "DotDict":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(value)
        raise TypeError(f"Expected dict or {cls.__name__}, got {type(value).__name__}")

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.dict_schema(
                keys_schema=core_schema.str_schema(),
                values_schema=core_schema.any_schema(),
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: v.deep_dump() if v is not None else None,
                return_schema=core_schema.dict_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        from pydantic_core import core_schema

        return handler(
            core_schema.dict_schema(
                keys_schema=core_schema.str_schema(),
                values_schema=core_schema.any_schema(),
            )
        )


class DotList(list):
    def __init__(self, iterable=None):
        super().__init__(map(_wrap, iterable) if iterable else ())

    def append(self, item):
        super().append(_copy_wrap(item))

    def extend(self, iterable):
        for item in iterable:
            self.append(item)

    def insert(self, index, item):
        super().insert(index, _copy_wrap(item))

    def __setitem__(self, key, value):
        super().__setitem__(key, _copy_wrap(value))

    def model_dump(self):
        return [v.model_dump() if hasattr(v, "model_dump") else v for v in self]

    def deep_dump(self):
        """Recursively convert to plain list — single-pass replacement for deepcopy(model_dump())."""
        return [
            item.deep_dump() if isinstance(item, (DotDict, DotList)) else copy.deepcopy(item)
            for item in self
        ]

    @classmethod
    def _validate(cls, value: object) -> "DotList":
        if isinstance(value, cls):
            return value
        if isinstance(value, (list, tuple)):
            return cls(value)
        raise TypeError(f"Expected list or {cls.__name__}, got {type(value).__name__}")

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.list_schema(items_schema=core_schema.any_schema()),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: v.deep_dump() if v is not None else None,
                return_schema=core_schema.list_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        from pydantic_core import core_schema

        return handler(core_schema.list_schema(items_schema=core_schema.any_schema()))


# Exact leaf types JSON decodes to. Wrapping checks them by identity first: an isinstance
# check against the Mapping ABC is several times slower and dominated the cost of wrapping
# large payloads such as a message history. Subclasses take the generic isinstance path.
_SCALAR_TYPES = frozenset({str, int, float, bool, type(None)})


def _wrap(data):
    """Already-wrapped DotDict/DotList is returned as-is (same instance, not copied) to avoid
    exponential re-wrapping cost on deep nesting; caller and result then share mutations.

    Only safe where the caller cannot keep a reference to `data` — i.e. inside
    DotDict/DotList construction. External mutations use `_copy_wrap`.
    """
    data_type = type(data)
    if data_type in _SCALAR_TYPES or data_type is DotDict or data_type is DotList:
        return data
    if data_type is dict:
        return DotDict(data)
    if data_type is list:
        return DotList(data)
    if isinstance(data, (DotDict, DotList)):
        return data
    if isinstance(data, Mapping):
        return DotDict(data)
    elif isinstance(data, (list, tuple, set)):
        return DotList(data)
    return data


def _copy_wrap(data):
    """Wrap a value coming from outside, copying every DotDict/DotList found in it.

    Assigning an already-wrapped value would otherwise alias it, so a later mutation of
    either side would be visible on the other and `variables.snapshot = variables` would
    build a reference cycle that `deep_dump()` and `json.dumps()` cannot walk. Leaf values
    that are neither mappings nor sequences keep their identity, as on construction.
    """
    data_type = type(data)
    if data_type in _SCALAR_TYPES:
        return data
    if data_type is list or data_type is DotList:
        return DotList([_copy_wrap(item) for item in data])
    if data_type is dict or data_type is DotDict or isinstance(data, Mapping):
        return DotDict({key: _copy_wrap(value) for key, value in data.items()})
    if isinstance(data, (list, tuple, set)):
        return DotList([_copy_wrap(item) for item in data])
    return data


def DotObject(data):  # noqa: N802
    """Wrap `data` into a DotDict/DotList (aliasing constructor, not copying).

    Already-wrapped DotDict/DotList values inside `data` are aliased, not copied.
    To get a detached copy, call deep_dump() on the result.
    """
    return _wrap(data)
