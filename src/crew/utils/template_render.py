import string
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_FORMATTER = string.Formatter()


@dataclass(frozen=True)
class RenderedTemplate:
    text: str
    # Placeholders with no value, in order of appearance; each is left in `text` as written.
    missing: tuple[str, ...] = ()
    # Why `text` is the template as written, with nothing substituted; None when rendered.
    unrendered_reason: str | None = None


def render_template(template: str, values: Mapping[str, Any]) -> RenderedTemplate:
    """Substitute `{name}` placeholders in a flow author's template with `str(values[name])`.

    Uses the `str.format` grammar, so `{{` and `}}` are literal braces, but a placeholder is
    only ever a plain lookup in `values`. `str.format` would also follow `{name.attribute}` and
    `{name[key]}` through the value and apply `!r` / `:spec`; a chain such as
    `{obj.update.__globals__[...]}` walks from a value into module globals and the process
    environment. A template holding such a placeholder, or one that does not parse (a JSON
    example such as `{"a": 1}`, a lone brace), is returned as written, which is what the
    callers did when `str.format` raised.
    """
    try:
        parts = list(_FORMATTER.parse(template))
    except ValueError as error:
        return RenderedTemplate(text=template, unrendered_reason=str(error))

    chunks: list[str] = []
    missing: list[str] = []
    for literal_text, field_name, format_spec, conversion in parts:
        chunks.append(literal_text)
        if field_name is None:
            continue
        if not _is_plain_lookup(field_name):
            return RenderedTemplate(
                text=template,
                unrendered_reason=f"placeholder '{field_name}' is not a plain variable name",
            )
        if format_spec or conversion:
            return RenderedTemplate(
                text=template,
                unrendered_reason=f"placeholder '{field_name}' uses a conversion or format spec",
            )
        if field_name in values:
            chunks.append(str(values[field_name]))
        else:
            missing.append(field_name)
            chunks.append("{" + field_name + "}")
    return RenderedTemplate(text="".join(chunks), missing=tuple(missing))


def _is_plain_lookup(field_name: str) -> bool:
    # Any name without `.` or `[` is a single key lookup in `str.format` too, so names such as
    # `user-id` keep working. An empty or all-digit name is positional there and has no value.
    return (
        bool(field_name)
        and not field_name.isdigit()
        and "." not in field_name
        and "[" not in field_name
    )
