from app.repositories.opensearch_query_compiler import compile as compile_filters


def _filter_clauses(query: dict) -> list[dict]:
    return query["bool"]["filter"]


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
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {"wildcard": {"name": {"value": "*Session*", "case_insensitive": True}}}


def test_compile_error_contains_targets_error_raw_not_error():
    node = {"field": "error", "op": "contains", "value": "AuthenticationError"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert "error.raw" in compiled_leaf["wildcard"]
    assert "error" not in compiled_leaf["wildcard"]


def test_compile_flattened_numeric_op_uses_runtime_script_not_range():
    node = {"field": "output.tokens", "op": "gt", "value": 500}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    scripted = compiled_leaf["bool"]["filter"][1]
    assert "script" in scripted
    assert scripted["script"]["script"]["params"]["value"] == 500.0
    assert "range" not in compiled_leaf


def test_compile_mixed_structured_and_flattened_and():
    node = {
        "op": "and",
        "children": [
            {"field": "status", "op": "equals", "value": "failed"},
            {"field": "tool", "op": "contains", "value": "Web Search"},
        ],
    }
    query = compile_filters(node, org_id=1, retention_days=0)
    and_clause = _filter_clauses(query)[-1]
    inner_clauses = and_clause["bool"]["filter"]
    assert {"term": {"status": "failed"}} in inner_clauses
    assert any(
        c.get("wildcard", {}).get("details.tool", {}).get("value") == "*Web Search*"
        for c in inner_clauses
    )


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
    assert {"term": {"org_id": 999}} in clauses  # the bypassed leaf, harmless alongside the real one


def test_compile_free_text_uses_wildcard_and_query_string():
    node = {"field": "__text__", "op": "contains", "value": "est3285"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    should = compiled_leaf["bool"]["should"]
    assert any("query_string" in c for c in should)
    assert any("name" in c.get("wildcard", {}) for c in should)


def test_compile_extra_filters_scopes_session_tree():
    query = compile_filters(
        {"field": "kind", "op": "in", "value": ["event"]},
        org_id=1,
        retention_days=0,
        extra_filters=[{"term": {"session_id": 42}}],
    )
    assert {"term": {"session_id": 42}} in _filter_clauses(query)
