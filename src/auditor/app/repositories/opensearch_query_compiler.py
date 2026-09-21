"""
Compiles a validated FilterNode AST (app/filtering/ast.py) into an
OpenSearch `query` clause. This is the ONLY place that knows whether a
field is a top-level mapped column or a dotted path into a `flat_object`
(input/output/details) - a plain lookup against the index mapping, not a
class hierarchy. Never exposed outside this module.

Why every clause lives in `bool.filter`, never `bool.must`/`should` at the
top level: result ordering here is always `event_time desc, id desc`
(enforced once, in the repository) - never by relevance score. Since
nothing ever sorts by `_score`, there is no reason to ever pay for score
computation: every leaf clause - including wildcard/query_string ones that
would traditionally live in `must` for scoring - is safe and strictly
cheaper inside a non-scoring `filter` context (OpenSearch still evaluates
the same match, it just skips scoring and gets the segment-level bitset
caching that only non-scoring clauses are eligible for). `should` is only
used for genuine OR semantics (with `minimum_should_match: 1`), and an
`or` subtree still ends up non-scoring overall once its parent wraps it in
`filter`.
"""

import json
from pathlib import Path
from typing import Any

from app.filtering.ast import FilterNode, FilterError

_MAPPING_PATH = (
    Path(__file__).resolve().parents[1]
    / "index_setup"
    / "0001_create_audit_events_index.json"
)
_FLAT_OBJECT_ROOTS = frozenset({"input", "output", "details"})


def _load_structured_fields() -> frozenset[str]:
    mapping = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
    properties = mapping["mappings"]["properties"]
    return frozenset(name for name in properties if name not in _FLAT_OBJECT_ROOTS)


_STRUCTURED_FIELDS = _load_structured_fields()

# Deep-filter field names (from the shared AST's KNOWN_FIELDS) to their
# actual dotted path into `details` - an OpenSearch-path concern, so it
# lives here rather than in the AST module.
DEEP_FILTER_ALIASES: dict[str, str] = {
    "agent": "details.agent_id",
    "tool": "details.tool",
    "task": "details.description",
    "prompt": "details.prompt_text",
    "message_text": "details.text",
    "message_thought": "details.thought",
}

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


def is_structured_field(field: str) -> bool:
    return field.lower() in _STRUCTURED_FIELDS


def is_flattened_path(field: str) -> bool:
    return field.lower().split(".", 1)[0] in _FLAT_OBJECT_ROOTS


def _resolve_deep_alias(field: str) -> str:
    return DEEP_FILTER_ALIASES.get(field.lower(), field)


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


def _free_text_clause(term: str) -> dict:
    """Lifted verbatim from the pre-AST `search` param in
    opensearch_repository.py: wildcard over the keyword identity fields,
    query_string relevance search over the flat_object blobs."""
    return {
        "bool": {
            "should": [
                {"wildcard": {field: {"value": f"*{term}*", "case_insensitive": True}}}
                for field in ("name", "node_type", "flow_name")
            ]
            + [
                {
                    "query_string": {
                        "query": term,
                        "fields": ["input.*", "output.*", "details.*"],
                        "default_operator": "AND",
                        "lenient": True,
                    }
                }
            ],
            "minimum_should_match": 1,
        }
    }


def _compile_numeric_runtime_filter(path: str, op: str, value: Any) -> dict:
    """flat_object `exists` on the full dotted path only resolves correctly
    one level below root, so it's dropped in favor of the script's own
    `fv == null` check; a root-only `exists` is kept as a safe pre-filter.
    """
    comparator = _PAINLESS_COMPARATORS[op]
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
                                "value": float(value),
                            },
                        }
                    }
                },
            ]
        }
    }


def _compile_error_leaf(op: str, value: Any) -> dict:
    """Always targets `error.raw` (wildcard subfield), never analyzed
    `error` text - the standard analyzer tokenizes '.' as a word-joiner, so
    a `match` on "AuthenticationError" inside a dotted stack-trace string
    finds nothing (documented in index_setup/README.md, verified against
    real litellm errors)."""
    if op == "is_empty":
        return {"bool": {"must_not": [{"exists": {"field": "error"}}]}}
    if op == "is_not_empty":
        return {"exists": {"field": "error"}}
    if op in _WILDCARD_PATTERN_BUILDERS:
        return _wildcard_clause("error.raw", op, value)
    raise FilterCompileError(f"Unsupported op {op!r} for field 'error'")


def _compile_structured_leaf(field: str, op: str, value: Any) -> dict:
    field = field.lower()
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


def _compile_flattened_leaf(field: str, op: str, value: Any) -> dict:
    path = _normalize_flattened_path(_resolve_deep_alias(field))

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


def _compile_leaf(field: str, op: str, value: Any) -> dict:
    if field == "__text__":
        return _free_text_clause(value)
    if field.lower() == "error":
        return _compile_error_leaf(op, value)
    if is_flattened_path(field) or field.lower() in DEEP_FILTER_ALIASES:
        return _compile_flattened_leaf(field, op, value)
    return _compile_structured_leaf(field, op, value)


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


def _compile_and_children(children: list[FilterNode]) -> list[dict]:
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
        compiled = _compile_node(child)
        if _is_pure_filter_conjunction(compiled):
            flat.extend(compiled["bool"]["filter"])
        else:
            flat.append(compiled)
    return flat


def _compile_node(node: FilterNode) -> dict:
    op = node.get("op")
    if op == "and":
        return {"bool": {"filter": _compile_and_children(node["children"])}}
    if op == "or":
        return {
            "bool": {
                "should": [_compile_node(c) for c in node["children"]],
                "minimum_should_match": 1,
            }
        }
    if op == "not":
        return {"bool": {"must_not": [_compile_node(node["child"])]}}
    return _compile_leaf(node["field"], node["op"], node.get("value"))


def scoped_query(
    extra_clauses: list[dict], *, org_id: int, retention_days: int
) -> dict:
    """
    Injects org_id/retention_days on top of arbitrary extra filter clauses.
    Shared by `compile()` below (for client AST-derived queries) and by the
    match-scope/duration-filter follow-up queries (app/services/), which
    need the same org/retention scoping on hand-built clauses (e.g.
    `terms: {parent_id: [...]}`) that never went through the AST at all -
    one place that knows how org/retention scoping is injected, not two.
    """
    filter_clauses: list[dict] = [{"term": {"org_id": org_id}}]
    if retention_days and retention_days > 0:
        filter_clauses.append(
            {"range": {"event_time": {"gte": f"now-{retention_days}d"}}}
        )
    filter_clauses.extend(extra_clauses)
    return {"bool": {"filter": filter_clauses}}


def compile(
    filter_node: FilterNode | None, *, org_id: int, retention_days: int
) -> dict:
    """
    The only entry point for client-supplied filters.
    """
    clauses = []
    if filter_node is not None:
        compiled = _compile_node(filter_node)
        if _is_pure_filter_conjunction(compiled):
            clauses.extend(compiled["bool"]["filter"])
        else:
            clauses.append(compiled)
    return scoped_query(clauses, org_id=org_id, retention_days=retention_days)
