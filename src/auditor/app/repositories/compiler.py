from typing import Any

from app.domains.base import BaseScopeArgs, FieldCatalog, FreeTextFields, ScopingPolicy
from app.filtering.ast import FREE_TEXT_FIELD, FilterError, FilterNode

_WILDCARD_PATTERN_BUILDERS = {
    "contains": lambda v: f"*{v}*",
    "not_contains": lambda v: f"*{v}*",
    "starts_with": lambda v: f"{v}*",
    "ends_with": lambda v: f"*{v}",
    "equals": lambda v: f"{v}",
    "not_equal": lambda v: f"{v}",
}

_NEGATED_OPS = frozenset({"not_contains", "not_equal", "key_not_equals", "not_in"})

_PAINLESS_COMPARATORS = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}


class FilterCompileError(FilterError):
    pass


def _normalize_flattened_path(field: str) -> str:
    """Only the root segment (input/output/details) is case-normalized -
    everything after the first '.' is a real, case-sensitive JSON key and
    must be preserved verbatim."""
    if "." in field:
        root, rest = field.split(".", 1)
        return f"{root.lower()}.{rest}"
    return field.lower()


def _wildcard_clause(field: str, op: str, value: Any) -> dict:
    pattern = _WILDCARD_PATTERN_BUILDERS[op](value)
    clause = {"wildcard": {field: {"value": pattern, "case_insensitive": True}}}
    if op in _NEGATED_OPS:
        return {"bool": {"must_not": [clause]}}
    return clause


def _free_text_clause(term: str, free_text: FreeTextFields) -> dict:
    should: list[dict] = [
        {"wildcard": {field: {"value": f"*{term}*", "case_insensitive": True}}}
        for field in free_text.wildcard_fields
    ]
    if free_text.query_string_fields:
        should.append(
            {
                "query_string": {
                    "query": term,
                    "fields": list(free_text.query_string_fields),
                    "default_operator": "AND",
                    "lenient": True,
                }
            }
        )
    if not should:
        raise FilterCompileError("Free-text search is not supported for this audit domain")
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _compile_numeric_runtime_filter(path: str, op: str, value: Any) -> dict:
    """flat_object `exists` on the full dotted path only resolves correctly
    one level below root, so it's dropped in favor of the script's own
    `fv == null` check; a root-only `exists` is kept as a safe pre-filter.
    """
    comparator = _PAINLESS_COMPARATORS[op]
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise FilterCompileError(f"op {op!r} on {path!r} requires a numeric value") from exc
    root = path.split(".", 1)[0]
    source = (
        "def fv = doc[params.path]; "
        "if (fv == null) { return false; } "
        "String prefix = params.root + '.' + params.path + '='; "
        "for (entry in fv) { "
        "if (entry.startsWith(prefix)) { "
        "String valueStr = entry.substring(prefix.length()); "
        "double d; "
        "try { d = Double.parseDouble(valueStr); } "
        "catch (Exception e) { return false; } "
        f"return d {comparator} params.value; "
        "} "
        "} "
        "return false;"
    )
    return {
        "bool": {
            "filter": [
                {"exists": {"field": root}},
                {
                    "script": {
                        "script": {
                            "lang": "painless",
                            "source": source,
                            "params": {
                                "path": path,
                                "root": root,
                                "value": threshold,
                            },
                        }
                    }
                },
            ]
        }
    }


def _compile_structured_leaf(
    field: str, op: str, value: Any, *, wildcard_subfield: str | None
) -> dict:
    field = field.lower()
    if wildcard_subfield is not None and op in _WILDCARD_PATTERN_BUILDERS:
        return _wildcard_clause(wildcard_subfield, op, value)
    if op == "equals":
        return {"term": {field: value}}
    if op == "not_equal":
        return {"bool": {"must_not": [{"term": {field: value}}]}}
    if op == "in":
        return {"terms": {field: value}}
    if op == "not_in":
        return {"bool": {"must_not": [{"terms": {field: value}}]}}
    if op in _PAINLESS_COMPARATORS:
        return {"range": {field: {op: value}}}
    if op == "is_empty":
        return {"bool": {"must_not": [{"exists": {"field": field}}]}}
    if op == "is_not_empty":
        return {"exists": {"field": field}}
    if op in _WILDCARD_PATTERN_BUILDERS:
        return _wildcard_clause(field, op, value)
    raise FilterCompileError(f"Unsupported op {op!r} for structured field {field!r}")


def _compile_key_existence_filter(path: str, *, negate: bool) -> dict:
    """flat_object `exists`-depth bug, but here `exists` IS the
    correctness check (no fallback script) - so presence is read via
    `doc[path].size()` instead, at every depth, for both directions.
    """
    comparator = "==" if negate else "!="
    empty_result = "true" if negate else "false"
    source = (
        "def fv = doc[params.path]; "
        f"if (fv == null) {{ return {empty_result}; }} "
        f"return fv.size() {comparator} 0;"
    )
    return {
        "bool": {
            "filter": [
                {
                    "script": {
                        "script": {
                            "lang": "painless",
                            "source": source,
                            "params": {"path": path},
                        }
                    }
                },
            ]
        }
    }


def _is_pure_filter_conjunction(compiled: dict) -> bool:
    """True when `compiled` is exactly `{"bool": {"filter": [...]}}` with no
    sibling `must`/`should`/`must_not` key - i.e. splicing its inner list
    into a surrounding `bool.filter` array is a pure flattening (same set of
    ANDed clauses), never a semantic change."""
    return (
        isinstance(compiled, dict)
        and set(compiled.keys()) == {"bool"}
        and set(compiled["bool"].keys()) == {"filter"}
    )


class QueryCompiler:
    def __init__(self, catalog: FieldCatalog, scoping: ScopingPolicy):
        self._catalog = catalog
        self._scoping = scoping

    def compile(self, filter_node, *, org_id, retention_days, **kwargs):
        """
        The only entry point for client-supplied filters.
        """
        clauses = []
        if filter_node is not None:
            compiled = self._compile_node(filter_node)
            if _is_pure_filter_conjunction(compiled):
                clauses.extend(compiled["bool"]["filter"])
            else:
                clauses.append(compiled)
        return self._scoping(clauses, BaseScopeArgs(org_id, retention_days), **kwargs)

    def _compile_node(self, node: FilterNode) -> dict:
        op = node.get("op")
        if op == "and":
            return {"bool": {"filter": self._compile_and_children(node["children"])}}
        if op == "or":
            return {
                "bool": {
                    "should": [self._compile_node(c) for c in node["children"]],
                    "minimum_should_match": 1,
                }
            }
        if op == "not":
            return {"bool": {"must_not": [self._compile_node(node["child"])]}}
        return self._compile_leaf(node["field"], node["op"], node.get("value"))

    def _compile_and_children(self, children: list[FilterNode]) -> list[dict]:
        """Compile every child of an `and` node and flatten out any nested pure
        `bool.filter` conjunction into this level's filter list instead of
        nesting bool-in-bool.

        This is a query-shape optimization only, not a behavior change: an AND
        of ANDs matches exactly the same documents either way. The point is to
        put every leaf clause - including cheap, highly-selective ones like
        org_id/retention scoping or a plain `term`/`terms` filter - as a direct
        sibling of expensive `must_not`/`should` negation clauses in one flat
        array, so OpenSearch's conjunction cost-based clause ordering (used in
        scoring-free `filter` context) can weigh all of them together rather
        than treating a nested `and` subtree as one opaque clause it can't look
        inside of."""
        flat: list[dict] = []
        for child in children:
            compiled = self._compile_node(child)
            if _is_pure_filter_conjunction(compiled):
                flat.extend(compiled["bool"]["filter"])
            else:
                flat.append(compiled)
        return flat

    def _compile_leaf(self, field: str, op: str, value: Any) -> dict:
        if field == FREE_TEXT_FIELD:
            return _free_text_clause(value, self._catalog.free_text_fields())
        resolved = self._catalog.resolve_alias(field)
        if self._catalog.is_flattened_path(resolved):
            return self._compile_flattened_leaf(field, op, value)
        return _compile_structured_leaf(
            field, op, value, wildcard_subfield=self._catalog.wildcard_subfield(field)
        )

    def _compile_flattened_leaf(self, field: str, op: str, value: Any) -> dict:
        path = _normalize_flattened_path(self._catalog.resolve_alias(field))

        if op in ("key_exists", "not_null"):
            return _compile_key_existence_filter(path, negate=False)
        if op in ("key_not_exists", "null"):
            return _compile_key_existence_filter(path, negate=True)
        if op in ("equals", "key_equals_value"):
            return {"term": {path: value}}
        if op in ("not_equal", "key_not_equals"):
            return {"bool": {"must_not": [{"term": {path: value}}]}}
        if op == "in":
            return {"terms": {path: value}}
        if op == "not_in":
            return {"bool": {"must_not": [{"terms": {path: value}}]}}
        if op in ("contains", "not_contains", "starts_with", "ends_with"):
            return _wildcard_clause(path, op, value)
        if op in _PAINLESS_COMPARATORS:
            return _compile_numeric_runtime_filter(path, op, value)
        raise FilterCompileError(f"Unsupported op {op!r} for flattened field {field!r}")
