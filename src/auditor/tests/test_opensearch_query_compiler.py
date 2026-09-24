import pytest

from app.domains.base import DEFAULT_SCOPING, BaseScopeArgs, MissingScopeError
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.repositories.compiler import QueryCompiler

_compiler = QueryCompiler(SESSIONS_FIELDS, DEFAULT_SCOPING)


def compile_filters(node, *, org_id, retention_days):
    """Thin wrapper so every test below (written against the old free
    `compile()` function) keeps working unchanged against the new
    QueryCompiler(catalog, scoping).compile(...) instance-method shape."""
    return _compiler.compile(node, org_id=org_id, retention_days=retention_days)


def _filter_clauses(query: dict) -> list[dict]:
    return query["bool"]["filter"]


def _scripted_clause(clauses: list[dict]) -> dict:
    """ScopingPolicy puts the caller's compiled clause(s) first in the
    filter array and always appends org_id/retention scoping clauses after
    them (see app/domains/base.py::ScopingPolicy.__call__) - so `[-1]` is
    never a safe way to grab "the leaf's own compiled clause" once org/
    retention scoping is injected. Locate the script clause by shape
    instead of by position."""
    return next(c for c in clauses if "script" in c)


def test_compile_always_injects_org_and_retention():
    query = compile_filters(None, org_id=42, retention_days=30)
    clauses = _filter_clauses(query)
    assert {"term": {"org_id": 42}} in clauses
    assert {"range": {"event_time": {"gte": "now-30d"}}} in clauses


def test_compile_no_retention_when_zero():
    query = compile_filters(None, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    assert not any("range" in c and "event_time" in c.get("range", {}) for c in clauses)


def test_compile_structured_field_uses_filter_clause():
    node = {"field": "status", "op": "equals", "value": "failed"}
    query = compile_filters(node, org_id=1, retention_days=0)
    assert {"term": {"status": "failed"}} in _filter_clauses(query)


def test_compile_contains_op_uses_wildcard_not_term():
    node = {"field": "name", "op": "contains", "value": "Session"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {
        "wildcard": {"name": {"value": "*Session*", "case_insensitive": True}}
    }


def test_compile_flow_name_contains_uses_wildcard_not_term():
    node = {"field": "flow_name", "op": "contains", "value": "Onboarding"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {
        "wildcard": {"flow_name": {"value": "*Onboarding*", "case_insensitive": True}}
    }


def test_compile_flow_name_not_contains_negates_wildcard():
    node = {"field": "flow_name", "op": "not_contains", "value": "Onboarding"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {
        "bool": {
            "must_not": [
                {
                    "wildcard": {
                        "flow_name": {"value": "*Onboarding*", "case_insensitive": True}
                    }
                }
            ]
        }
    }


def test_compile_error_contains_targets_error_raw_not_error():
    node = {"field": "error", "op": "contains", "value": "AuthenticationError"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert "error.raw" in compiled_leaf["wildcard"]
    assert "error" not in compiled_leaf["wildcard"]


def test_compile_flattened_numeric_op_uses_runtime_script_not_range():
    """No full-path `exists` guard (flat_object `exists` is only correct
    1 level below root - see _compile_numeric_runtime_filter); a root-only
    `exists` pre-filter is kept as a safe-at-any-depth optimization."""
    node = {"field": "output.tokens", "op": "gt", "value": 500}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    scripted = _scripted_clause(clauses)
    assert "script" in scripted
    assert scripted["script"]["script"]["params"]["value"] == 500.0
    assert {"exists": {"field": "output"}} in clauses
    assert not any("range" in c for c in clauses)


def test_compile_numeric_flattened_filter_reads_via_doc_not_source():
    """`params._source` is unavailable in a filter-context script (verified
    live - resolves to null), so the value must be read via `doc[...]`."""
    node = {"field": "details.tokens_used", "op": "gt", "value": 5000}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    scripted = _scripted_clause(clauses)
    source = scripted["script"]["script"]["source"]

    assert "params._source" not in source
    assert "doc[params.path]" in source
    assert scripted["script"]["script"]["params"]["path"] == "details.tokens_used"
    assert scripted["script"]["script"]["params"]["root"] == "details"
    assert scripted["script"]["script"]["params"]["value"] == 5000.0
    # No full-path `exists` guard - only the safe root-only pre-filter.
    assert {"exists": {"field": "details"}} in clauses
    assert not any("exists" in c and c["exists"]["field"] != "details" for c in clauses)


def test_compile_numeric_deeply_nested_flattened_filter_has_no_full_path_exists_guard():
    """A 2+-level path must never compile a full-path `exists` guard
    (silently 0 matches on real OpenSearch) - only the root-only
    pre-filter plus the script's own null-check."""
    node = {
        "field": "output.token_usage.completion_tokens",
        "op": "gt",
        "value": 100,
    }
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    scripted = _scripted_clause(clauses)

    assert "script" in scripted
    assert {"exists": {"field": "output"}} in clauses
    assert not any("exists" in c and c["exists"]["field"] != "output" for c in clauses)
    assert (
        scripted["script"]["script"]["params"]["path"]
        == "output.token_usage.completion_tokens"
    )
    assert scripted["script"]["script"]["params"]["root"] == "output"
    assert scripted["script"]["script"]["params"]["value"] == 100.0


def test_compile_key_exists_deep_path_uses_script_not_native_exists():
    """`key_exists`/`not_null` must not compile to native `exists` on a
    2+-level path (same flat_object exists-depth bug, no script fallback
    here) - must use the depth-agnostic `doc[path].size() != 0` script."""
    node = {"field": "output.token_usage.completion_tokens", "op": "key_exists"}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    scripted = _scripted_clause(clauses)

    assert not any("exists" in c for c in clauses)
    assert "script" in scripted
    source = scripted["script"]["script"]["source"]
    assert "doc[params.path]" in source
    assert "!= 0" in source
    assert (
        scripted["script"]["script"]["params"]["path"]
        == "output.token_usage.completion_tokens"
    )


def test_compile_key_not_exists_deep_path_uses_script_not_native_must_not_exists():
    """Negated direction: `must_not`-wrapped native `exists` on a 2+-level
    path used to match every doc, not just ones missing the key - must use
    the same script, checking `== 0` instead of `!= 0`."""
    node = {"field": "output.token_usage.completion_tokens", "op": "key_not_exists"}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    scripted = _scripted_clause(clauses)

    assert not any("exists" in c for c in clauses)
    assert not any("must_not" in c.get("bool", {}) for c in clauses)
    assert "script" in scripted
    source = scripted["script"]["script"]["source"]
    assert "doc[params.path]" in source
    assert "== 0" in source
    assert (
        scripted["script"]["script"]["params"]["path"]
        == "output.token_usage.completion_tokens"
    )


def test_compile_not_null_and_null_aliases_use_same_key_existence_script():
    """`not_null`/`null` are aliases for `key_exists`/`key_not_exists` -
    must compile identically, not a separate path that could drift."""
    exists_via_alias = compile_filters(
        {"field": "details.a.b", "op": "not_null"}, org_id=1, retention_days=0
    )
    exists_via_canonical = compile_filters(
        {"field": "details.a.b", "op": "key_exists"}, org_id=1, retention_days=0
    )
    assert _scripted_clause(_filter_clauses(exists_via_alias)) == _scripted_clause(
        _filter_clauses(exists_via_canonical)
    )

    not_exists_via_alias = compile_filters(
        {"field": "details.a.b", "op": "null"}, org_id=1, retention_days=0
    )
    not_exists_via_canonical = compile_filters(
        {"field": "details.a.b", "op": "key_not_exists"}, org_id=1, retention_days=0
    )
    assert _scripted_clause(_filter_clauses(not_exists_via_alias)) == _scripted_clause(
        _filter_clauses(not_exists_via_canonical)
    )


def test_compile_key_exists_shallow_path_also_uses_script():
    """Script-based check applies at every depth, even 0/1 where native
    `exists` happens to work - one code path, not depth-branching."""
    node = {"field": "output.iterations", "op": "key_exists"}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)

    assert not any("exists" in c for c in clauses)
    assert "script" in _scripted_clause(clauses)


def test_compile_numeric_flattened_filter_script_semantics_simulated():
    """Simulates the compiled Painless script's actual logic in Python (no
    JVM available in unit tests - see test_search_integration.py for the
    live-OpenSearch equivalent, run against the real cluster to confirm this
    simulation matches reality): `doc[path]` on a flat_object sub-key
    doesn't hand back just that key's value - it returns doc-values for
    every key under the root object, each formatted as
    `"<root>.<root>.<leaf_path>=<value>"` (confirmed live, e.g.
    `"details.details.tokens_used=8001"`). The script has to find its own
    key's entry by that prefix before parsing the value."""
    node = {"field": "details.tokens_used", "op": "gt", "value": 5000}
    query = compile_filters(node, org_id=1, retention_days=0)
    params = _scripted_clause(_filter_clauses(query))["script"]["script"]["params"]
    threshold = params["value"]
    prefix = f"{params['root']}.{params['path']}="

    def _simulated_script(doc_values: list[str]) -> bool:
        for entry in doc_values:
            if entry.startswith(prefix):
                value_str = entry[len(prefix) :]
                try:
                    d = float(value_str)
                except ValueError:
                    return False
                return d > threshold
        return False

    assert _simulated_script(["details.details.tokens_used=6000"]) is True
    assert _simulated_script(["details.details.tokens_used=100"]) is False
    assert _simulated_script(["details.details.test_batch=f03_tokens"]) is False
    assert _simulated_script([]) is False
    assert _simulated_script(["details.details.tokens_used=not-a-number"]) is False


def test_compile_mixed_structured_and_flattened_and():
    """A top-level `and` of two plain leaves is a pure filter conjunction,
    so it gets flattened directly into the outer org_id/retention filter
    array - both leaves land as direct siblings of org_id, not nested one
    level deeper inside their own `bool.filter` wrapper. Same match
    semantics (still an AND of all three), flatter shape."""
    node = {
        "op": "and",
        "children": [
            {"field": "status", "op": "equals", "value": "failed"},
            {"field": "tool", "op": "contains", "value": "Web Search"},
        ],
    }
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    assert {"term": {"org_id": 1}} in clauses
    assert {"term": {"status": "failed"}} in clauses
    assert any(
        c.get("wildcard", {}).get("details.tool", {}).get("value") == "*Web Search*"
        for c in clauses
    )
    # No nested `bool.filter` wrapper left over for this AND - it was fully
    # flattened into the top-level array.
    assert not any(
        isinstance(c, dict) and set(c.keys()) == {"bool"} and "filter" in c["bool"]
        for c in clauses
    )


def test_compile_negation_sibling_stays_a_flat_filter_clause():
    """Mirrors stress-test filter #6's shape:
    `not agent = "x" and (status = "completed" or status = "failed")`.
    The `not` and `or` branches must land as direct siblings of org_id in
    one flat `bool.filter` array - never nested one level deeper inside an
    opaque `bool.filter` wrapper for the `and` - so OpenSearch's
    conjunction cost-based clause ordering can weigh the cheap org_id/status
    clauses against the expensive negation together, not as a single
    opaque nested clause."""
    node = {
        "op": "and",
        "children": [
            {
                "op": "not",
                "child": {"field": "agent", "op": "equals", "value": "agent-bot-1"},
            },
            {
                "op": "or",
                "children": [
                    {"field": "status", "op": "equals", "value": "completed"},
                    {"field": "status", "op": "equals", "value": "failed"},
                ],
            },
        ],
    }
    query = compile_filters(node, org_id=1, retention_days=30)
    clauses = _filter_clauses(query)

    assert {"term": {"org_id": 1}} in clauses
    assert {"range": {"event_time": {"gte": "now-30d"}}} in clauses
    assert {
        "bool": {"must_not": [{"term": {"details.agent_id": "agent-bot-1"}}]}
    } in clauses
    assert {
        "bool": {
            "should": [
                {"term": {"status": "completed"}},
                {"term": {"status": "failed"}},
            ],
            "minimum_should_match": 1,
        }
    } in clauses
    # Exactly 4 flat siblings - no leftover nested `bool.filter` wrapper for
    # the `and` node itself.
    assert len(clauses) == 4


def test_compile_never_lets_client_ast_touch_org_id():
    # org_id isn't in KNOWN_FIELDS at all - validate_filter_node (tested
    # separately) rejects this before compile() is ever reached; compile()
    # itself doesn't special-case org_id either, so even a bypassed/raw
    # client leaf just gets treated as an ordinary (meaningless) term query,
    # never overriding the injected org scoping clause.
    node = {"field": "org_id", "op": "equals", "value": 999}
    query = compile_filters(node, org_id=1, retention_days=0)
    clauses = _filter_clauses(query)
    assert {"term": {"org_id": 1}} in clauses
    assert {
        "term": {"org_id": 999}
    } in clauses  # the bypassed leaf, harmless alongside the real one


def test_compile_free_text_uses_wildcard_and_query_string():
    node = {"field": "__text__", "op": "contains", "value": "est3285"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    should = compiled_leaf["bool"]["should"]
    assert any("query_string" in c for c in should)
    assert any("name" in c.get("wildcard", {}) for c in should)


def test_compile_flattened_alias_in_op_uses_terms():
    node = {"field": "agent", "op": "in", "value": ["some_id"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {"terms": {"details.agent_id": ["some_id"]}}


def test_compile_flattened_alias_not_in_op_uses_must_not_terms():
    node = {"field": "agent", "op": "not_in", "value": ["some_id", "other_id"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {
        "bool": {"must_not": [{"terms": {"details.agent_id": ["some_id", "other_id"]}}]}
    }


def test_compile_tool_alias_in_op_uses_terms():
    node = {"field": "tool", "op": "in", "value": ["Web Search"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {"terms": {"details.tool": ["Web Search"]}}


def test_compile_tool_alias_not_in_op_uses_must_not_terms():
    node = {"field": "tool", "op": "not_in", "value": ["Web Search"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {
        "bool": {"must_not": [{"terms": {"details.tool": ["Web Search"]}}]}
    }


def test_compile_session_id_in_op_uses_structured_terms():
    node = {"field": "session_id", "op": "in", "value": [8, 9]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {"terms": {"session_id": [8, 9]}}


def test_compile_session_message_id_in_op_uses_structured_terms():
    node = {"field": "session_message_id", "op": "in", "value": [1, 2, 3]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[0]
    assert compiled_leaf == {"terms": {"session_message_id": [1, 2, 3]}}


# --- ScopingPolicy fails closed instead of compiling an unscoped query ---


def test_scoping_policy_raises_when_called_without_base_args():
    with pytest.raises(TypeError):
        # base_args is a required positional argument now - a call site that
        # forgets to supply it must fail loudly (TypeError) rather than
        # silently compile an org-unscoped query.
        DEFAULT_SCOPING([])  # type: ignore[call-arg]


def test_scoping_policy_raises_when_base_args_is_none():
    with pytest.raises(MissingScopeError):
        DEFAULT_SCOPING([], None)


def test_scoping_policy_raises_when_org_id_is_none():
    with pytest.raises(MissingScopeError):
        # A malformed caller could still build a BaseScopeArgs with
        # org_id=None at runtime (dataclasses don't enforce type hints) -
        # the policy itself must refuse to compile in that case too.
        DEFAULT_SCOPING([], BaseScopeArgs(org_id=None, retention_days=0))
