"""
Shared filter AST for the audit search endpoint.

One tree shape for everything: the visual quick/deep filter panel, the
textual query language (query_language.py), and saved presets all produce -
or consume - this exact structure. There is no field-kind class hierarchy
here; KNOWN_FIELDS is a plain lookup used only to reject unknown
field/op combinations early (400, before ever reaching OpenSearch). The
separate question of "is this field a top-level OpenSearch column or a
dotted flat_object path" belongs entirely to the OpenSearch compiler
(repositories/opensearch_query_compiler.py) - this module never answers it.

FilterNode shape:
    {"op": "and" | "or", "children": [FilterNode, ...]}
  | {"op": "not", "child": FilterNode}
  | {"field": str, "op": str, "value": Any}   # leaf
"""

from typing import Any, Iterator, NamedTuple

FilterNode = dict[str, Any]

FLAT_OBJECT_ROOTS = frozenset({"input", "output", "details"})

# Canonical leaf op vocabulary. The query-language parser normalizes its
# symbols (=, !=, :, !:, >, <, >=, <=) onto these same names, so the AST
# never has to care which front-end produced a leaf.
_TEXT_CONDITION_OPS = frozenset(
    {
        "equals",
        "contains",
        "starts_with",
        "ends_with",
        "not_contains",
        "not_equal",
        "is_empty",
        "is_not_empty",
    }
)

_FLATTENED_OPS = frozenset(
    {
        "equals",
        "key_exists",
        "key_not_exists",
        "key_equals_value",
        "key_not_equals",
        "contains",
        "starts_with",
        "ends_with",
        "not_contains",
        "lt",
        "gt",
        "lte",
        "gte",
        "null",
        "not_null",
    }
)

_SELECT_OPS = frozenset({"in", "not_in", "equals", "not_equal"})

_RANGE_OPS = frozenset({"equals", "gt", "lt", "gte", "lte"})

_DURATION_OPS = frozenset(
    {"gt", "lt", "gte", "lte", "equals", "is_empty", "is_not_empty"}
)


class FieldSpec(NamedTuple):
    allowed_ops: frozenset[str]
    # True only for `duration` - not translatable to OpenSearch DSL at all;
    # split_duration_filter() must remove every leaf using this field before
    # the remainder AST reaches the OpenSearch compiler.
    computed: bool = False


KNOWN_FIELDS: dict[str, FieldSpec] = {
    # main fields
    "id": FieldSpec(_RANGE_OPS | _SELECT_OPS),
    "session_id": FieldSpec(_SELECT_OPS),
    "session_message_id": FieldSpec(_SELECT_OPS),
    "status": FieldSpec(_SELECT_OPS),
    "kind": FieldSpec(_SELECT_OPS),
    "name": FieldSpec(_TEXT_CONDITION_OPS),
    "flow_name": FieldSpec(_SELECT_OPS),
    "node_type": FieldSpec(_SELECT_OPS),
    "run_type": FieldSpec(_SELECT_OPS),
    "event_time": FieldSpec(_RANGE_OPS),
    "error": FieldSpec(_TEXT_CONDITION_OPS),
    # additional fields
    "agent": FieldSpec(_SELECT_OPS),
    "tool": FieldSpec(_SELECT_OPS),
    "task": FieldSpec(_TEXT_CONDITION_OPS),
    "prompt": FieldSpec(_TEXT_CONDITION_OPS),
    "message_text": FieldSpec(_TEXT_CONDITION_OPS),
    "message_thought": FieldSpec(_TEXT_CONDITION_OPS),
    "duration": FieldSpec(_DURATION_OPS, computed=True),
    # special fields
    "__text__": FieldSpec(frozenset({"contains"})),
}

_FLATTENED_PATH_SPEC = FieldSpec(_FLATTENED_OPS)


class FilterError(Exception):
    """Base for every filter-AST error. app/main.py maps this to HTTP 400."""


class FilterValidationError(FilterError):
    pass


class FilterParseError(FilterError):
    pass


def _resolve_field_spec(field: str, *, path: str) -> FieldSpec:
    lower = field.lower()
    if lower in KNOWN_FIELDS:
        return KNOWN_FIELDS[lower]
    # Either a bare flat_object root (`input : est3285` - search anywhere in
    # the whole blob) or a dotted path into one (`input.prompt` - a specific
    # key) - both resolve to the same op set; the OpenSearch compiler is what
    # tells them apart when building the actual query.
    root = lower.split(".", 1)[0]
    if root in FLAT_OBJECT_ROOTS:
        return _FLATTENED_PATH_SPEC
    raise FilterValidationError(f"{path}: {field!r} is not a known filterable field")


def validate_filter_node(
    node: FilterNode, *, allow_computed: bool = True, _path: str = "filters"
) -> None:
    """
    Recursive structural + field/op whitelist check. Raises
    FilterValidationError on the first problem found, with a path-qualified
    message. `allow_computed=False` is used by the OpenSearch-compiler entry
    point to assert no `duration` leaves reach it after split_duration_filter
    has run - defensive, since the splitter is what actually removes them.
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
                child, allow_computed=allow_computed, _path=f"{_path}.children[{i}]"
            )
        return

    if op == "not":
        child = node.get("child")
        if child is None:
            raise FilterValidationError(f"{_path}: 'not' requires a 'child'")
        validate_filter_node(
            child, allow_computed=allow_computed, _path=f"{_path}.child"
        )
        return

    field = node.get("field")
    leaf_op = node.get("op")
    if not isinstance(field, str) or not field:
        raise FilterValidationError(f"{_path}: leaf node missing a 'field' string")
    if not isinstance(leaf_op, str) or not leaf_op:
        raise FilterValidationError(f"{_path}: leaf node missing an 'op' string")

    spec = _resolve_field_spec(field, path=_path)
    if spec.computed and not allow_computed:
        raise FilterValidationError(
            f"{_path}: field {field!r} is computed and cannot reach the OpenSearch "
            "compiler directly - it must be extracted by split_duration_filter first"
        )
    if leaf_op not in spec.allowed_ops:
        raise FilterValidationError(
            f"{_path}: op {leaf_op!r} is not valid for field {field!r} "
            f"(allowed: {sorted(spec.allowed_ops)})"
        )
    if leaf_op in ("in", "not_in") and not isinstance(node.get("value"), list):
        raise FilterValidationError(f"{_path}: op {leaf_op!r} requires a list 'value'")


def iter_leaves(node: FilterNode) -> Iterator[FilterNode]:
    """Flatten every leaf out of an AST, depth-first. Reused by the
    OpenSearch compiler (to check field usage) and split_duration_filter."""
    op = node.get("op")
    if op in ("and", "or"):
        for child in node.get("children", []):
            yield from iter_leaves(child)
    elif op == "not":
        yield from iter_leaves(node.get("child", {}))
    else:
        yield node
