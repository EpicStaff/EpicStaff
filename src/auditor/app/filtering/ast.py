"""
Shared filter AST for the audit search endpoint.

One tree shape for everything: the visual quick/deep filter panel, the
textual query language (query_language.py), and saved presets all produce -
or consume - this exact structure. There is no field-kind class hierarchy
here; KNOWN_FIELDS is a plain lookup used only to reject unknown
field/op combinations early (400, before ever reaching OpenSearch). The
separate question of "is this field a top-level OpenSearch column or a
dotted flat_object path" belongs entirely to the OpenSearch compiler
(repositories/compiler.py) - this module never answers it.

FilterNode shape:
    {"op": "and" | "or", "children": [FilterNode, ...]}
  | {"op": "not", "child": FilterNode}
  | {"field": str, "op": str, "value": Any}   # leaf
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from app.domains.base import FieldCatalog

FilterNode = dict[str, Any]

# AST leaf field produced for a free-text term (bare word or `text:` prefix).
FREE_TEXT_FIELD = "__text__"


class FieldSpec(NamedTuple):
    allowed_ops: frozenset[str]
    # Not translatable to OpenSearch DSL at all; must match one of the
    # domain's ComputedField implementations (asserted by AuditDomain) so
    # split_computed_leaves() removes the leaf before compilation.
    computed: bool = False
    allowed_values: frozenset[str] | None = None


class FilterError(Exception):
    """Base for every filter-AST error. app/main.py maps this to HTTP 400."""


class FilterValidationError(FilterError):
    pass


class FilterParseError(FilterError):
    pass


def _resolve_field_spec(catalog: FieldCatalog, field: str, *, path: str) -> FieldSpec:
    specs = catalog.field_spec(field)
    if specs is None:
        raise FilterValidationError(f"{path}: {field!r} is not a known filterable field")
    return specs


def validate_filter_node(
    catalog: FieldCatalog,
    node: FilterNode,
    *,
    _path: str = "filters",
) -> None:
    """
    Recursive structural + field/op whitelist check. Raises
    FilterValidationError on the first problem found, with a path-qualified
    message.
    """
    if not isinstance(node, dict):
        raise FilterValidationError(f"{_path}: expected an object, got {type(node).__name__}")

    op = node.get("op")

    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise FilterValidationError(f"{_path}: '{op}' requires a non-empty 'children' list")
        for i, child in enumerate(children):
            validate_filter_node(catalog, child, _path=f"{_path}.children[{i}]")
        return

    if op == "not":
        child = node.get("child")
        if child is None:
            raise FilterValidationError(f"{_path}: 'not' requires a 'child'")
        validate_filter_node(catalog, child, _path=f"{_path}.child")
        return

    field = node.get("field")
    leaf_op = node.get("op")
    if not isinstance(field, str) or not field:
        raise FilterValidationError(f"{_path}: leaf node missing a 'field' string")
    if not isinstance(leaf_op, str) or not leaf_op:
        raise FilterValidationError(f"{_path}: leaf node missing an 'op' string")

    spec = _resolve_field_spec(catalog, field, path=_path)
    if leaf_op not in spec.allowed_ops:
        raise FilterValidationError(
            f"{_path}: op {leaf_op!r} is not valid for field {field!r} "
            f"(allowed: {sorted(spec.allowed_ops)})"
        )
    if leaf_op in ("in", "not_in") and not isinstance(node.get("value"), list):
        raise FilterValidationError(f"{_path}: op {leaf_op!r} requires a list 'value'")
    if spec.allowed_values is not None:
        raw_value = node.get("value")
        candidates = raw_value if isinstance(raw_value, list) else [raw_value]
        invalid = [v for v in candidates if v not in spec.allowed_values]
        if invalid:
            raise FilterValidationError(
                f"{_path}: value(s) {invalid!r} not allowed for field {field!r} "
                f"(allowed: {sorted(spec.allowed_values)})"
            )


def iter_leaves(node: FilterNode) -> Iterator[FilterNode]:
    """Flatten every leaf out of an AST, depth-first. Reused by the
    OpenSearch compiler (to check field usage) and split_computed_leaves."""
    op = node.get("op")
    if op in ("and", "or"):
        for child in node.get("children", []):
            yield from iter_leaves(child)
    elif op == "not":
        yield from iter_leaves(node.get("child", {}))
    else:
        yield node
