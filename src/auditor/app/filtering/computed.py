"""
Generic, domain-free splitting of "computed" filter leaves (fields that
have no OpenSearch representation at all - e.g. `duration` - and so can
never be pushed into a compiled query) out of a FilterNode AST.

A computed leaf may only ever appear directly under a top-level `and`,
never under `or`/`not`: correctly evaluating e.g. "... or duration > 5"
against a computed field needs full boolean-tree evaluation over the whole
candidate set post-fetch - materially bigger scope than "AND one
post-filter on top of the OpenSearch query". Rejected outright rather than
silently mishandled.

Which field names count as "computed", and how their leaves combine into
a usable condition, is domain data (AuditDomain.computed, a tuple of
ComputedField - see app/domains/base.py) - a Protocol this module depends
on without knowing about any concrete domain.
"""

from typing import Any

from app.domains.base import ComputedField
from app.filtering.ast import FilterNode, FilterValidationError, iter_leaves


def _is_computed_leaf(node: FilterNode, computed_fields: frozenset[str]) -> bool:
    return node.get("field", "").lower() in computed_fields


def _split(
    node: FilterNode, computed_fields: frozenset[str]
) -> tuple[FilterNode | None, list[FilterNode]]:
    op = node.get("op")

    if op == "and":
        remainders: list[FilterNode] = []
        computed_leaves: list[FilterNode] = []
        for child in node["children"]:
            child_remainder, child_computed = _split(child, computed_fields)
            if child_remainder is not None:
                remainders.append(child_remainder)
            computed_leaves.extend(child_computed)
        if not remainders:
            remainder = None
        elif len(remainders) == 1:
            remainder = remainders[0]
        else:
            remainder = {"op": "and", "children": remainders}
        return remainder, computed_leaves

    if op in ("or", "not"):
        for leaf in iter_leaves(node):
            if _is_computed_leaf(leaf, computed_fields):
                field = leaf.get("field", "")
                raise FilterValidationError(
                    f"{field!r} cannot be combined with '{op}' - only a "
                    "top-level AND of computed-field conditions is supported"
                )
        return node, []

    if _is_computed_leaf(node, computed_fields):
        return None, [node]
    return node, []


def split_computed_leaves(
    node: FilterNode | None, *, computed: tuple[ComputedField, ...]
) -> tuple[FilterNode | None, dict[str, Any]]:
    """Extracts every computed-field leaf out of the AST (they must only
    ever appear directly under a top-level `and`, never under `or`/`not` -
    enforced above), groups them by field name, and combines each group via
    that field's own `combine()` (e.g. into a DurationCondition). Returns
    (remainder AST with those leaves removed, {field_name: condition} -
    empty dict if none present)."""
    combiner_by_name = {field.name: field for field in computed}
    computed_field_names = frozenset(combiner_by_name)

    if node is None:
        return None, {}

    remainder, leaves = _split(node, computed_field_names)
    if not leaves:
        return remainder, {}

    leaves_by_field: dict[str, list[FilterNode]] = {}
    for leaf in leaves:
        leaves_by_field.setdefault(leaf["field"].lower(), []).append(leaf)

    conditions = {
        field_name: combiner_by_name[field_name].combine(field_leaves)
        for field_name, field_leaves in leaves_by_field.items()
    }
    return remainder, conditions
