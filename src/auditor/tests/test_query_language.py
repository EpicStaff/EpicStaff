import pytest

from app.domains.sessions.computed import SESSIONS_COMPUTED
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.filtering.ast import FilterParseError, FilterValidationError, validate_filter_node
from app.filtering.computed import split_computed_leaves
from app.filtering.query_language import ast_to_query_text, parse_query
from app.domains.base import DEFAULT_SCOPING
from app.repositories.compiler import QueryCompiler

QUERIES = {
    'status in ["error", "warning"] or tool in ["Web_Search_Tool", "Notification_Tool"]': {
        "op": "or",
        "children": [
            {"field": "status", "op": "in", "value": ["error", "warning"]},
            {"field": "tool", "op": "in", "value": ["Web_Search_Tool", "Notification_Tool"]},
        ],
    },
    'name == "Session Start"': {"field": "name", "op": "equals", "value": "Session Start"},
    "Error is not empty and not ID == 66": {
        "op": "and",
        "children": [
            {"field": "Error", "op": "is_not_empty"},
            {"op": "not", "child": {"field": "ID", "op": "equals", "value": 66}},
        ],
    },
    "input : order1234 and output !: Greetings": {
        "op": "and",
        "children": [
            {"field": "input", "op": "contains", "value": "order1234"},
            {"field": "output", "op": "not_contains", "value": "Greetings"},
        ],
    },
    'flow_name : "Onboarding"': {"field": "flow_name", "op": "contains", "value": "Onboarding"},
    "duration >= 5 and duration <= 9": {
        "op": "and",
        "children": [
            {"field": "duration", "op": "gte", "value": 5},
            {"field": "duration", "op": "lte", "value": 9},
        ],
    },
    "duration > 5 and duration < 9 and status != failed": {
        "op": "and",
        "children": [
            {"field": "duration", "op": "gt", "value": 5},
            {"field": "duration", "op": "lt", "value": 9},
            {"field": "status", "op": "not_equal", "value": "failed"},
        ],
    },
    "serper": {"field": "__text__", "op": "contains", "value": "serper"},
    "text: serper": {"field": "__text__", "op": "contains", "value": "serper"},
    'name starts with "Session"': {"field": "name", "op": "starts_with", "value": "Session"},
    "name STARTS WITH Session": {"field": "name", "op": "starts_with", "value": "Session"},
    "name ends with Finish": {"field": "name", "op": "ends_with", "value": "Finish"},
    "details.retry_count exists": {"field": "details.retry_count", "op": "key_exists"},
    "details.retry_count NOT EXISTS": {"field": "details.retry_count", "op": "key_not_exists"},
    'status not in ("completed", "failed")': {
        "field": "status",
        "op": "not_in",
        "value": ["completed", "failed"],
    },
    "not details.retry_count exists and name ends with 3": {
        "op": "and",
        "children": [
            {"op": "not", "child": {"field": "details.retry_count", "op": "key_exists"}},
            {"field": "name", "op": "ends_with", "value": 3},
        ],
    },
    # Keywords of the new operators stay ordinary free-text words on their own.
    "starts": {"field": "__text__", "op": "contains", "value": "starts"},
    "exists": {"field": "__text__", "op": "contains", "value": "exists"},
    'text: "starts with"': {"field": "__text__", "op": "contains", "value": "starts with"},
}


@pytest.mark.parametrize(("query", "expected_ast"), QUERIES.items(), ids=list(QUERIES))
def test_query_parses_to_the_filter_tree(query, expected_ast):
    assert parse_query(query) == expected_ast


@pytest.mark.parametrize("query", QUERIES, ids=list(QUERIES))
def test_filter_tree_prints_back_to_an_equivalent_query(query):
    ast = parse_query(query)

    assert parse_query(ast_to_query_text(ast)) == ast


@pytest.mark.parametrize(
    ("node", "expected_text"),
    [
        ({"field": "name", "op": "starts_with", "value": "Session"}, 'name starts with "Session"'),
        ({"field": "name", "op": "ends_with", "value": "Finish"}, 'name ends with "Finish"'),
        ({"field": "details.retry_count", "op": "key_exists"}, "details.retry_count exists"),
        ({"field": "details.retry_count", "op": "key_not_exists"}, "details.retry_count not exists"),
        (
            {"field": "details.retry_count", "op": "key_not_equals", "value": 3},
            "details.retry_count != 3",
        ),
    ],
)
def test_builder_only_ops_print_as_query_text(node, expected_text):
    assert ast_to_query_text(node) == expected_text


def _compiled_leaf(node) -> dict:
    compiler = QueryCompiler(SESSIONS_FIELDS, DEFAULT_SCOPING)
    return compiler.compile(node, org_id=1, retention_days=0)["bool"]["filter"][0]


@pytest.mark.parametrize(
    ("node", "expected_clause"),
    [
        (
            {"field": "details.retry_count", "op": "key_not_equals", "value": 3},
            {"bool": {"must_not": [{"term": {"details.retry_count": 3}}]}},
        ),
        (
            {"field": "input", "op": "key_not_equals", "value": "x"},
            {"bool": {"must_not": [{"term": {"input": "x"}}]}},
        ),
    ],
    ids=["details-path", "input-root"],
)
def test_key_not_equals_printed_as_query_text_is_accepted_and_matches_the_same(
    node, expected_clause
):
    parsed = parse_query(ast_to_query_text(node))

    validate_filter_node(SESSIONS_FIELDS, parsed)
    assert parsed["op"] == "not_equal"
    assert _compiled_leaf(parsed) == _compiled_leaf(node) == expected_clause


def test_not_after_field_requires_in_or_exists():
    with pytest.raises(FilterParseError, match="Expected 'in' or 'exists' after 'not'"):
        parse_query("status not completed")


def test_bare_word_followed_by_partial_keyword_phrase_is_not_a_comparison():
    # `starts` without `with` must not be taken as an operator - the bare word
    # falls back to free text, so the leftover words are trailing input.
    with pytest.raises(FilterParseError, match="Unexpected trailing input 'starts'"):
        parse_query("name starts Session")


def test_in_accepts_both_paren_and_bracket_spelling():
    assert parse_query('status in ("error", "warning")') == parse_query(
        'status in ["error", "warning"]'
    )


@pytest.mark.parametrize(
    "node",
    [
        {"field": "details.tool", "op": "equals", "value": "Web Search Tool"},
        {"field": "flow_name", "op": "contains", "value": "Onboarding"},
        {"field": "flow_name", "op": "not_contains", "value": "Onboarding"},
        {"field": "status", "op": "equals", "value": "completed"},
        {"field": "status", "op": "not_equal", "value": "failed"},
        {"field": "status", "op": "in", "value": ["completed", "failed"]},
    ],
)
def test_valid_filter_is_accepted(node):
    validate_filter_node(SESSIONS_FIELDS, node)


@pytest.mark.parametrize(
    "node",
    [
        {"field": "org_id", "op": "equals", "value": 1},
        {"field": "message_thought", "op": "contains", "value": "x"},
        {"field": "duration", "op": "contains", "value": 5},
        # status is Literal["completed", "failed"]; anything else would later fail
        # deserialization on the read path instead of being a 400 here.
        {"field": "status", "op": "equals", "value": "error"},
        {"field": "status", "op": "in", "value": ["completed", "warning"]},
    ],
    ids=["org-id", "removed-field", "op-not-allowed-for-field", "unknown-status", "unknown-status-in-list"],
)
def test_invalid_filter_is_rejected(node):
    with pytest.raises(FilterValidationError):
        validate_filter_node(SESSIONS_FIELDS, node)


@pytest.mark.parametrize(
    "node",
    [
        {
            "op": "or",
            "children": [
                {"field": "status", "op": "equals", "value": "failed"},
                {"field": "duration", "op": "gt", "value": 5},
            ],
        },
        {"op": "not", "child": {"field": "duration", "op": "gt", "value": 5}},
    ],
    ids=["under-or", "under-not"],
)
def test_computed_field_is_only_allowed_in_a_plain_conjunction(node):
    with pytest.raises(FilterValidationError):
        split_computed_leaves(node, computed=SESSIONS_COMPUTED)


def test_computed_field_conditions_are_combined_and_split_from_the_rest():
    remainder, conditions = split_computed_leaves(
        {
            "op": "and",
            "children": [
                {"field": "status", "op": "equals", "value": "failed"},
                {"field": "duration", "op": "gt", "value": 10},
                {"field": "duration", "op": "lt", "value": 100},
            ],
        },
        computed=SESSIONS_COMPUTED,
    )

    assert remainder == {"field": "status", "op": "equals", "value": "failed"}
    duration = conditions["duration"]
    assert [duration.matches(value) for value in (5, 10, 50, 100, 200)] == [
        False, False, True, False, False,
    ]
