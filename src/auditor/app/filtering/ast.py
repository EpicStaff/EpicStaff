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

from typing import Any, Iterator, NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.domains.base import FieldCatalog

FilterNode = dict[str, Any]


class FieldSpec(NamedTuple):
    allowed_ops: frozenset[str]
    # True only for `duration` - not translatable to OpenSearch DSL at all;
    # split_computed_leaves() (app/filtering/computed.py) must remove every
    # leaf using this field before the remainder AST reaches the OpenSearch
    # compiler.
    computed: bool = False
    allowed_values: frozenset[str] | None = None


class FilterError(Exception):
    """Base for every filter-AST error. app/main.py maps this to HTTP 400."""


class FilterValidationError(FilterError):
    pass


class FilterParseError(FilterError):
    pass


def _resolve_field_spec(catalog: "FieldCatalog", field: str, *, path: str) -> FieldSpec:
    specs = catalog.field_spec(field)
    if specs is None:
        raise FilterValidationError(
            f"{path}: {field!r} is not a known filterable field"
        )
    return specs


def validate_filter_node(
    catalog: "FieldCatalog",
    node: FilterNode,
    *,
    allow_computed: bool = True,
    _path: str = "filters",
) -> None:
    """
    Recursive structural + field/op whitelist check. Raises
    FilterValidationError on the first problem found, with a path-qualified
    message. `allow_computed=False` is used by the OpenSearch-compiler entry
    point to assert no `duration` leaves reach it after split_computed_leaves
    (app/filtering/computed.py) has run - defensive, since the splitter is
    what actually removes them.
    """
    if not isinstance(node, dict):
        raise FilterValidationError(
            f"{_path}: expected an object, got {type(node).__name__}"
        )

    op = node.get("op")

    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise FilterValidationError(
                f"{_path}: '{op}' requires a non-empty 'children' list"
            )
        for i, child in enumerate(children):
            validate_filter_node(
                catalog,
                child,
                allow_computed=allow_computed,
                _path=f"{_path}.children[{i}]",
            )
        return

    if op == "not":
        child = node.get("child")
        if child is None:
            raise FilterValidationError(f"{_path}: 'not' requires a 'child'")
        validate_filter_node(
            catalog, child, allow_computed=allow_computed, _path=f"{_path}.child"
        )
        return

    field = node.get("field")
    leaf_op = node.get("op")
    if not isinstance(field, str) or not field:
        raise FilterValidationError(f"{_path}: leaf node missing a 'field' string")
    if not isinstance(leaf_op, str) or not leaf_op:
        raise FilterValidationError(f"{_path}: leaf node missing an 'op' string")

    spec = _resolve_field_spec(catalog, field, path=_path)
    if spec.computed and not allow_computed:
        raise FilterValidationError(
            f"{_path}: field {field!r} is computed and cannot reach the OpenSearch "
            "compiler directly - it must be extracted by split_computed_leaves first"
        )
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
