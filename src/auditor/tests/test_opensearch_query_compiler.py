"""The OpenSearch query the compiler sends for each filter.

The query DSL is the boundary to OpenSearch, and no OpenSearch runs in CI, so the
compiled clauses are asserted directly. test_search_integration.py runs the semantic
equivalents against a live cluster.
"""

import pytest

from app.domains.base import DEFAULT_SCOPING, BaseScopeArgs, MissingScopeError
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.repositories.compiler import QueryCompiler

_compiler = QueryCompiler(SESSIONS_FIELDS, DEFAULT_SCOPING)


def _clauses(node, *, org_id=1, retention_days=0) -> list[dict]:
    return _compiler.compile(node, org_id=org_id, retention_days=retention_days)["bool"]["filter"]


def _leaf(node) -> dict:
    """The caller's own clause; org and retention scoping always come after it."""
    return _clauses(node)[0]


def _wildcard(path: str, value: str) -> dict:
    return {"wildcard": {path: {"value": f"*{value}*", "case_insensitive": True}}}


def _must_not(clause: dict) -> dict:
    return {"bool": {"must_not": [clause]}}


@pytest.mark.parametrize(
    ("retention_days", "expected_retention_clause"),
    [(30, {"range": {"event_time": {"gte": "now-30d"}}}), (0, None)],
    ids=["retention-limited", "unlimited-retention"],
)
def test_every_query_is_scoped_to_the_callers_org_and_retention(
    retention_days, expected_retention_clause
):
    clauses = _clauses(None, org_id=42, retention_days=retention_days)

    assert {"term": {"org_id": 42}} in clauses
    retention_clauses = [c for c in clauses if "event_time" in c.get("range", {})]
    assert retention_clauses == ([expected_retention_clause] if expected_retention_clause else [])


@pytest.mark.parametrize(
    ("field", "op", "value", "expected"),
    [
        ("status", "equals", "failed", {"term": {"status": "failed"}}),
        ("name", "contains", "Session", _wildcard("name", "Session")),
        ("flow_name", "contains", "Onboarding", _wildcard("flow_name", "Onboarding")),
        ("flow_name", "not_contains", "Onboarding", _must_not(_wildcard("flow_name", "Onboarding"))),
        # `error` is analyzed text; pattern matching has to run on its raw keyword.
        ("error", "contains", "AuthenticationError", _wildcard("error.raw", "AuthenticationError")),
        ("agent", "in", ["some_id"], {"terms": {"details.agent_id": ["some_id"]}}),
        (
            "agent",
            "not_in",
            ["some_id", "other_id"],
            _must_not({"terms": {"details.agent_id": ["some_id", "other_id"]}}),
        ),
        ("tool", "equals", "Web_Search_Tool", {"term": {"details.data.name": "Web_Search_Tool"}}),
        ("tool", "in", ["Web_Search_Tool"], {"terms": {"details.data.name": ["Web_Search_Tool"]}}),
        (
            "tool",
            "not_in",
            ["Web_Search_Tool"],
            _must_not({"terms": {"details.data.name": ["Web_Search_Tool"]}}),
        ),
        ("task", "contains", "vendor", _wildcard("details.data.task.name", "vendor")),
        ("message_text", "contains", "vendor", _wildcard("details.data.message", "vendor")),
        ("session_id", "in", [8, 9], {"terms": {"session_id": [8, 9]}}),
        ("session_message_id", "in", [1, 2, 3], {"terms": {"session_message_id": [1, 2, 3]}}),
    ],
)
def test_filter_leaf_compiles_to_the_clause_on_the_fields_real_path(field, op, value, expected):
    assert _leaf({"field": field, "op": op, "value": value}) == expected


@pytest.mark.parametrize(
    ("path", "root"),
    [
        ("output.tokens", "output"),
        ("details.tokens_used", "details"),
        ("output.token_usage.completion_tokens", "output"),
    ],
)
def test_numeric_comparison_inside_a_flat_object_uses_a_script(path, root):
    """flat_object values are keywords, so a range query compares strings. Only a
    root-level `exists` pre-filter is safe: a full-path `exists` silently matches
    nothing below the first level."""
    clauses = _clauses({"field": path, "op": "gt", "value": 500})

    (script_clause,) = [c for c in clauses if "script" in c]
    script = script_clause["script"]["script"]
    assert script["params"] == {"path": path, "root": root, "value": 500.0}
    # params._source resolves to null in a filter-context script.
    assert "params._source" not in script["source"]
    assert [c for c in clauses if "exists" in c] == [{"exists": {"field": root}}]
    assert not any("range" in c for c in clauses)


@pytest.mark.parametrize("path", ["output.iterations", "output.token_usage.completion_tokens"])
@pytest.mark.parametrize(
    ("op", "negated"),
    [("key_exists", False), ("not_null", False), ("key_not_exists", True), ("null", True)],
)
def test_key_existence_uses_a_wildcard_on_the_sub_path_at_any_depth(path, op, negated):
    """Native `exists` and `doc[path]` both only see whether the root object is
    non-empty, so neither can tell one key from another."""
    present = {"wildcard": {path: {"value": "*"}}}

    assert _leaf({"field": path, "op": op}) == (_must_not(present) if negated else present)


def test_conjunction_branches_stay_flat_siblings_of_the_org_scope():
    """`not agent = "x" and (status = "completed" or status = "failed")` - the branches
    sit next to the cheap org/retention clauses so OpenSearch can order them by cost."""
    node = {
        "op": "and",
        "children": [
            {"op": "not", "child": {"field": "agent", "op": "equals", "value": "agent-bot-1"}},
            {
                "op": "or",
                "children": [
                    {"field": "status", "op": "equals", "value": "completed"},
                    {"field": "status", "op": "equals", "value": "failed"},
                ],
            },
        ],
    }

    clauses = _clauses(node, retention_days=30)

    assert sorted(clauses, key=repr) == sorted(
        [
            _must_not({"term": {"details.agent_id": "agent-bot-1"}}),
            {
                "bool": {
                    "should": [{"term": {"status": "completed"}}, {"term": {"status": "failed"}}],
                    "minimum_should_match": 1,
                }
            },
            {"term": {"org_id": 1}},
            {"range": {"event_time": {"gte": "now-30d"}}},
        ],
        key=repr,
    )


def test_free_text_searches_every_free_text_field():
    should = _leaf({"field": "__text__", "op": "contains", "value": "order1234"})["bool"]["should"]

    assert sorted(should, key=repr) == sorted(
        [
            _wildcard(field, "order1234")
            for field in ("name", "node_type", "flow_name", "input", "output", "details")
        ],
        key=repr,
    )


def test_client_filter_on_org_id_never_replaces_the_tokens_org_scope():
    """Validation rejects `org_id` before compiling; even a bypassed leaf only adds a
    second, narrowing term next to the real scope."""
    clauses = _clauses({"field": "org_id", "op": "equals", "value": 999}, org_id=1)

    assert {"term": {"org_id": 1}} in clauses


@pytest.mark.parametrize(
    "base_args",
    [None, BaseScopeArgs(org_id=None, retention_days=0)],
    ids=["no-scope-args", "no-org-id"],
)
def test_scoping_refuses_to_build_a_query_without_an_org(base_args):
    with pytest.raises(MissingScopeError):
        DEFAULT_SCOPING([], base_args)
