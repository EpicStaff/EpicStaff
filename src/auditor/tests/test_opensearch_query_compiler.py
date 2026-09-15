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
    assert compiled_leaf == {
        "wildcard": {"name": {"value": "*Session*", "case_insensitive": True}}
    }


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


def test_compile_numeric_flattened_filter_reads_via_doc_not_source():
    """Regression test for the silent-0-results bug: `params._source` is
    unavailable in a filter-context script query (verified live against the
    running OpenSearch cluster - it silently resolves to `null`), so the
    script must read the value via `doc[...]` instead."""
    node = {"field": "details.tokens_used", "op": "gt", "value": 5000}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    scripted = compiled_leaf["bool"]["filter"][1]
    source = scripted["script"]["script"]["source"]

    assert "params._source" not in source
    assert "doc[params.path]" in source
    assert scripted["script"]["script"]["params"]["path"] == "details.tokens_used"
    assert scripted["script"]["script"]["params"]["root"] == "details"
    assert scripted["script"]["script"]["params"]["value"] == 5000.0
    # exists check still guards against an absent key
    assert compiled_leaf["bool"]["filter"][0] == {
        "exists": {"field": "details.tokens_used"}
    }


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
    compiled_leaf = _filter_clauses(query)[-1]
    params = compiled_leaf["bool"]["filter"][1]["script"]["script"]["params"]
    threshold = params["value"]
    prefix = f"{params['root']}.{params['path']}="

    def _simulated_script(doc_values: list[str]) -> bool:
        for entry in doc_values:
            if entry.startswith(prefix):
                value_str = entry[len(prefix):]
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
    assert (
        _simulated_script(["details.details.tokens_used=not-a-number"]) is False
    )


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
    assert {
        "term": {"org_id": 999}
    } in clauses  # the bypassed leaf, harmless alongside the real one


def test_compile_free_text_uses_wildcard_and_query_string():
    node = {"field": "__text__", "op": "contains", "value": "est3285"}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    should = compiled_leaf["bool"]["should"]
    assert any("query_string" in c for c in should)
    assert any("name" in c.get("wildcard", {}) for c in should)


def test_compile_flattened_alias_in_op_uses_terms():
    node = {"field": "agent", "op": "in", "value": ["some_id"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {"terms": {"details.agent_id": ["some_id"]}}


def test_compile_flattened_alias_not_in_op_uses_must_not_terms():
    node = {"field": "agent", "op": "not_in", "value": ["some_id", "other_id"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {
        "bool": {"must_not": [{"terms": {"details.agent_id": ["some_id", "other_id"]}}]}
    }


def test_compile_tool_alias_in_op_uses_terms():
    node = {"field": "tool", "op": "in", "value": ["Web Search"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {"terms": {"details.tool": ["Web Search"]}}


def test_compile_tool_alias_not_in_op_uses_must_not_terms():
    node = {"field": "tool", "op": "not_in", "value": ["Web Search"]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {
        "bool": {"must_not": [{"terms": {"details.tool": ["Web Search"]}}]}
    }


def test_compile_session_id_in_op_uses_structured_terms():
    node = {"field": "session_id", "op": "in", "value": [8, 9]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {"terms": {"session_id": [8, 9]}}


def test_compile_session_message_id_in_op_uses_structured_terms():
    node = {"field": "session_message_id", "op": "in", "value": [1, 2, 3]}
    query = compile_filters(node, org_id=1, retention_days=0)
    compiled_leaf = _filter_clauses(query)[-1]
    assert compiled_leaf == {"terms": {"session_message_id": [1, 2, 3]}}
