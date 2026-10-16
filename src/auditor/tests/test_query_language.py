import pytest

from app.domains.sessions.computed import SESSIONS_COMPUTED
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.filtering.ast import FilterValidationError, validate_filter_node
from app.filtering.computed import split_computed_leaves
from app.filtering.query_language import ast_to_query_text, parse_query

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
}


@pytest.mark.parametrize(("query", "expected_ast"), QUERIES.items(), ids=list(QUERIES))
def test_query_parses_to_the_filter_tree(query, expected_ast):
    assert parse_query(query) == expected_ast


@pytest.mark.parametrize("query", QUERIES, ids=list(QUERIES))
def test_filter_tree_prints_back_to_an_equivalent_query(query):
    ast = parse_query(query)

    assert parse_query(ast_to_query_text(ast)) == ast


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
