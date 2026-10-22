"""Cleaning of text an external MCP server sends about its tools.

An MCP server is trusted to run its tools, not to write the model's prompt, yet a
tool's description and input schema both reach the model. They get the same
treatment: control characters removed and text capped.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

C0_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT_CHARS = 1024
_MAX_REPORTED_KEY_CHARS = 64

# Keywords whose string values must stay whole: a truncated pattern or reference
# breaks the schema, and required names must match the property keys.
_STRUCTURAL_KEYWORDS = frozenset(
    {
        "pattern",
        "$ref",
        "$id",
        "$schema",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "required",
        "dependentRequired",
    }
)
# Keywords whose values the model sends back to the server as they are, so they
# can be neither cleaned nor capped: a changed value fails the server's validation.
_EXACT_KEYWORDS = frozenset({"enum", "const"})
# Keywords whose values map names to sub-schemas (or, for dependentRequired, to
# lists of names): their keys are names, so a parameter called "enum" is not a keyword.
_NAME_MAP_KEYWORDS = frozenset(
    {
        "properties",
        "patternProperties",
        "$defs",
        "definitions",
        "dependentSchemas",
        "dependencies",
        "dependentRequired",
    }
)


class _Mode(Enum):
    TEXT = "text"  # control characters removed, capped
    STRUCTURAL = "structural"  # control characters removed, not capped
    EXACT = "exact"  # refused if it holds a control character, never changed


class UnsafeSchemaError(ValueError):
    """The schema cannot be passed to the model safely."""


def strip_control_chars(text: str) -> str:
    return C0_CONTROL_CHARS_RE.sub("", text)


def sanitize_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `schema` with control characters removed and text capped.

    Every string is cleaned and capped at MAX_TEXT_CHARS. Values that cutting
    would break are refused instead when longer than that: keys and enum/const
    values, which the model sends back to the server exactly, and structural
    values such as patterns. Keys and enum/const values are also refused rather
    than cleaned when they hold a control character, for the same reason.

    Raises:
        UnsafeSchemaError: A key or an enum/const value contains a control
            character, a value that cannot be cut is longer than MAX_TEXT_CHARS,
            or the schema is nested too deeply to walk.
    """
    try:
        return _sanitize_mapping(schema, mode=_Mode.TEXT, keys_are_names=False)
    except RecursionError as error:
        raise UnsafeSchemaError("schema is nested too deeply") from error


def _child_mode(keyword: str, mode: _Mode) -> _Mode:
    if mode is _Mode.EXACT or keyword in _EXACT_KEYWORDS:
        return _Mode.EXACT
    if keyword in _STRUCTURAL_KEYWORDS:
        return _Mode.STRUCTURAL
    return _Mode.TEXT


def _sanitize_mapping(
    mapping: dict[str, Any], *, mode: _Mode, keys_are_names: bool
) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in mapping.items():
        if C0_CONTROL_CHARS_RE.search(str(key)):
            raise UnsafeSchemaError(
                f"schema key {str(key)[:_MAX_REPORTED_KEY_CHARS]!r} contains control characters"
            )
        _refuse_if_too_long(str(key), "schema key")
        if keys_are_names:
            sanitized[key] = _sanitize_value(value, mode=mode)
        elif key in _NAME_MAP_KEYWORDS and isinstance(value, dict):
            sanitized[key] = _sanitize_mapping(
                value, mode=_child_mode(key, mode), keys_are_names=True
            )
        else:
            sanitized[key] = _sanitize_value(value, mode=_child_mode(key, mode))
    return sanitized


def _sanitize_value(value: Any, *, mode: _Mode) -> Any:
    if isinstance(value, str):
        return _sanitize_string(value, mode=mode)
    if isinstance(value, list):
        return [_sanitize_value(item, mode=mode) for item in value]
    if isinstance(value, dict):
        return _sanitize_mapping(value, mode=mode, keys_are_names=False)
    return value


def _sanitize_string(text: str, *, mode: _Mode) -> str:
    if mode is _Mode.EXACT:
        if C0_CONTROL_CHARS_RE.search(text):
            raise UnsafeSchemaError(
                f"enum or const value {text[:_MAX_REPORTED_KEY_CHARS]!r} contains control characters"
            )
        _refuse_if_too_long(text, "enum or const value")
        return text
    cleaned = strip_control_chars(text)
    if mode is _Mode.STRUCTURAL:
        _refuse_if_too_long(cleaned, "structural value")
        return cleaned
    return cleaned[:MAX_TEXT_CHARS]


def _refuse_if_too_long(text: str, what: str) -> None:
    """Refuse a value that cutting would break, so no string reaches the model longer than the cap."""
    if len(text) > MAX_TEXT_CHARS:
        raise UnsafeSchemaError(
            f"{what} {text[:_MAX_REPORTED_KEY_CHARS]!r}... is longer than {MAX_TEXT_CHARS} characters"
        )
