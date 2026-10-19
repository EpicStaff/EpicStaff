"""Domain dataclasses and rows share field names, so one pair of functions maps every table."""

import types
from dataclasses import fields
from enum import StrEnum
from typing import Union, get_args, get_origin


def _enum_type(annotation) -> type[StrEnum] | None:
    """The StrEnum a field holds, plain (`Mode`) or optional (`Role | None`, `Optional[Role]`).

    None for anything else, containers (`list[Role]`) and wider unions included: their stored
    value is not one enum member.
    """
    if get_origin(annotation) in (types.UnionType, Union):
        members = [member for member in get_args(annotation) if member is not type(None)]
        annotation = members[0] if len(members) == 1 else None
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return annotation
    return None


def to_domain[T](row, cls: type[T]) -> T:
    values = {}
    for item in fields(cls):
        value = getattr(row, item.name)
        enum_type = _enum_type(item.type)
        values[item.name] = enum_type(value) if enum_type and value is not None else value
    return cls(**values)


def values_of(obj, *, exclude: tuple[str, ...] = ()) -> dict:
    return {
        item.name: (str(value) if isinstance(value, StrEnum) else value)
        for item in fields(obj)
        if item.name not in exclude
        for value in (getattr(obj, item.name),)
    }


def to_row(obj, row_cls, *, exclude: tuple[str, ...] = ()):
    return row_cls(**values_of(obj, exclude=exclude))
