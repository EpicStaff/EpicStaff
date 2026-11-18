"""Placeholders in a flow author's text: task and agent instructions, knowledge queries and
classification prompts.

The grammar is `str.format`'s, so `{{` and `}}` are literal braces, but a placeholder only
ever reads data. Each placeholder is classified, first match wins:

1. POSITIONAL: the head is empty or a number (`{}`, `{0}`, `{.a}`, `{[0]}`, `{0[x]}`).
2. A conversion: `!r`, `!s` or `!a` after an identifier head is REFUSED (`{topic!r}`,
   `{a[b]!r}`); any other is FORMATTED (`{"hi!": 1}` parses as one).
3. FORMATTED: a format spec (`{topic:>10}`, a JSON example such as `{"a": 1}`).
4. VALUE: no `.` and no `[`; the exact key in `values` (`{user-id}`, `{first name}`, `{_x}`).
5. BAD_PATH: a path that does not parse (`{a..b}`, `{a[b]c}`, `{a[]}`).
6. REFUSED: a path segment, the head included, starts with `_` (`{a._b}`, `{_a.b}`, `{a[_b]}`).
7. VALUE: a path, read by item lookup only. `{a.b}` and `{a[b]}` both read key `b` of an
   exact `dict` (`{d[0]}` reads key `"0"`); `{a[0]}` reads an in-range index of an exact
   `list`. Any other value, subclasses included, ends the walk without an attribute or
   `__getitem__` call on it, and the placeholder is unresolved.

Rendering: a REFUSED placeholder anywhere raises RefusedPlaceholderError. Otherwise a template
that does not parse, or holds any placeholder that is not VALUE, is returned as written.
Otherwise each VALUE placeholder becomes `str(value)`; an unresolved one is listed in
`missing` and left in the text as written.
"""

import _string
import string
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_FORMATTER = string.Formatter()
_REFUSED_CONVERSIONS = ("r", "s", "a")
_UNRESOLVED = object()


class PlaceholderKind(StrEnum):
    VALUE = "value"
    REFUSED = "refused"
    POSITIONAL = "positional"
    FORMATTED = "formatted"
    BAD_PATH = "bad_path"


@dataclass(frozen=True)
class Placeholder:
    # The text between the braces as written, including any `!conversion` and `:spec`.
    field: str
    kind: PlaceholderKind
    # The head is a Python identifier, so the author most likely meant a variable.
    variable_like: bool
    # Author-facing; names only the placeholder, never a value. None for VALUE.
    reason: str | None
    # VALUE only: the head, then each key or index. Empty otherwise.
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class TemplateInspection:
    placeholders: tuple[Placeholder, ...]
    # The parser's message when the template does not parse; `placeholders` is empty then.
    parse_error: str | None


@dataclass(frozen=True)
class RenderedTemplate:
    text: str
    # Placeholders with no value, in order of appearance; each is left in `text` as written.
    missing: tuple[str, ...] = ()
    # Why `text` is the template as written, with nothing substituted; None when rendered.
    unrendered_reason: str | None = None


class RefusedPlaceholderError(Exception):
    """A template holds a placeholder that is never allowed; the text is safe to show."""

    def __init__(self, placeholder: Placeholder):
        super().__init__(placeholder.reason)
        self.placeholder = placeholder


def inspect_template(template: str) -> TemplateInspection:
    """Classify every placeholder of `template` by the rule in this module's docstring."""
    try:
        parts = _parse(template)
    except ValueError as error:
        return TemplateInspection(placeholders=(), parse_error=str(error))
    return TemplateInspection(
        placeholders=tuple(placeholder for _, placeholder in parts if placeholder is not None),
        parse_error=None,
    )


def render_template(template: str, values: Mapping[str, Any]) -> RenderedTemplate:
    """Fill the placeholders of `template` from `values` by the rule in this module's docstring.

    Raises:
        RefusedPlaceholderError: The template holds a REFUSED placeholder.
    """
    try:
        parts = _parse(template)
    except ValueError as error:
        return RenderedTemplate(text=template, unrendered_reason=str(error))

    placeholders = [placeholder for _, placeholder in parts if placeholder is not None]
    for placeholder in placeholders:
        if placeholder.kind is PlaceholderKind.REFUSED:
            raise RefusedPlaceholderError(placeholder)
    for placeholder in placeholders:
        if placeholder.kind is not PlaceholderKind.VALUE:
            return RenderedTemplate(text=template, unrendered_reason=placeholder.reason)

    chunks: list[str] = []
    missing: list[str] = []
    for literal_text, placeholder in parts:
        chunks.append(literal_text)
        if placeholder is None:
            continue
        value = _resolve(placeholder.path, values)
        if value is _UNRESOLVED:
            missing.append(placeholder.field)
            chunks.append("{" + placeholder.field + "}")
        else:
            chunks.append(str(value))
    return RenderedTemplate(text="".join(chunks), missing=tuple(missing))


def _parse(template: str) -> list[tuple[str, Placeholder | None]]:
    # Formatter.parse raises ValueError lazily, while being iterated; _classify never does.
    return [
        (literal_text, None if field_name is None else _classify(field_name, spec, conversion))
        for literal_text, field_name, spec, conversion in _FORMATTER.parse(template)
    ]


def _classify(field_name: str, format_spec: str, conversion: str | None) -> Placeholder:
    field = field_name
    if conversion is not None:
        field += f"!{conversion}"
    if format_spec:
        field += f":{format_spec}"

    try:
        head, rest = _string.formatter_field_name_split(field_name)
    except ValueError:
        # Raised only for a numeric head too long to be an index: still positional.
        return _non_value(field, PlaceholderKind.POSITIONAL, False, _positional_reason(field))
    variable_like = isinstance(head, str) and head.isidentifier()

    if isinstance(head, int) or not head or head.isdigit():
        return _non_value(
            field, PlaceholderKind.POSITIONAL, variable_like, _positional_reason(field)
        )
    if conversion is not None:
        if conversion in _REFUSED_CONVERSIONS and variable_like:
            return _non_value(
                field,
                PlaceholderKind.REFUSED,
                variable_like,
                f"Placeholder '{{{field}}}' is not allowed: conversions such as '!{conversion}' "
                f"are not supported. Write '{{{field_name}}}'.",
            )
        return _non_value(field, PlaceholderKind.FORMATTED, variable_like, _formatted_reason(field))
    if format_spec:
        return _non_value(field, PlaceholderKind.FORMATTED, variable_like, _formatted_reason(field))
    if "." not in field_name and "[" not in field_name:
        return Placeholder(field, PlaceholderKind.VALUE, variable_like, None, (field_name,))

    try:
        keys = [key for _, key in rest]
    except ValueError as error:
        return _non_value(
            field,
            PlaceholderKind.BAD_PATH,
            variable_like,
            f"Placeholder '{{{field}}}' is not a valid path: {error}.",
        )
    underscored = next(
        (key for key in (head, *keys) if isinstance(key, str) and key.startswith("_")), None
    )
    if underscored is not None:
        return _non_value(
            field,
            PlaceholderKind.REFUSED,
            variable_like,
            f"Placeholder '{{{field}}}' is not allowed: '{underscored}' starts with '_'. "
            "Rename that variable or key.",
        )
    return Placeholder(field, PlaceholderKind.VALUE, variable_like, None, (head, *keys))


def _non_value(field: str, kind: PlaceholderKind, variable_like: bool, reason: str) -> Placeholder:
    return Placeholder(field, kind, variable_like, reason, ())


def _positional_reason(field: str) -> str:
    return f"Placeholder '{{{field}}}' has no variable name, so it is never filled."


def _formatted_reason(field: str) -> str:
    return (
        f"Placeholder '{{{field}}}' has a format spec or conversion, which is not supported. "
        "If it is example text, write its braces as '{{' and '}}'."
    )


def _resolve(path: tuple[str | int, ...], values: Mapping[str, Any]) -> Any:
    head, *keys = path
    if head not in values:
        return _UNRESOLVED
    current = values[head]
    for key in keys:
        # Exact types only: a subclass or any other object may run code on lookup.
        if type(current) is dict and str(key) in current:
            current = current[str(key)]
        elif type(current) is list and type(key) is int and 0 <= key < len(current):
            current = current[key]
        else:
            return _UNRESOLVED
    return current
