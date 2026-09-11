import pytest

from app.filtering.ast import (
    FilterValidationError,
    validate_filter_node,
)
from app.filtering.query_language import (
    ast_to_query_text,
    parse_query,
    tokenize,
)
from app.services.duration_filter import split_duration_filter


def test_tokenize_operators():
    kinds_values = [(t.kind, t.value) for t in tokenize("a:b !: >= <= == != > <")]
    assert kinds_values == [
        ("IDENT", "a"),
        ("OP", ":"),
        ("IDENT", "b"),
        ("OP", "!:"),
        ("OP", ">="),
        ("OP", "<="),
        ("OP", "=="),
        ("OP", "!="),
        ("OP", ">"),
        ("OP", "<"),
        ("EOF", ""),
    ]


def test_parse_status_in_or_tool_in():
    ast = parse_query('status in ["error", "warning"] or tool in ["Web Search Tool", "Notification Tool"]')
    assert ast == {
        "op": "or",
        "children": [
            {"field": "status", "op": "in", "value": ["error", "warning"]},
            {"field": "tool", "op": "in", "value": ["Web Search Tool", "Notification Tool"]},
        ],
    }


def test_parse_name_equals():
    assert parse_query('name == "Session Start"') == {
        "field": "name",
        "op": "equals",
        "value": "Session Start",
    }


def test_parse_error_not_empty_and_not_id_eq():
    ast = parse_query("Error is not empty and not ID == 66")
    assert ast == {
        "op": "and",
        "children": [
            {"field": "Error", "op": "is_not_empty"},
            {"op": "not", "child": {"field": "ID", "op": "equals", "value": 66}},
        ],
    }


def test_parse_input_contains_and_output_contains():
    ast = parse_query("input : est3285 and output : Greetings")
    assert ast == {
        "op": "and",
        "children": [
            {"field": "input", "op": "contains", "value": "est3285"},
            {"field": "output", "op": "contains", "value": "Greetings"},
        ],
    }


def test_in_accepts_both_paren_and_bracket_spelling():
    assert parse_query('status in ("error", "warning")') == parse_query('status in ["error", "warning"]')


@pytest.mark.parametrize(
    "query",
    [
        'status in ["error", "warning"] or tool in ["Web Search Tool", "Notification Tool"]',
        'name == "Session Start"',
        "Error is not empty and not ID == 66",
        "input : est3285 and output : Greetings",
    ],
)
def test_roundtrip_ast_to_query_text(query):
    ast = parse_query(query)
    reparsed = parse_query(ast_to_query_text(ast))
    assert reparsed == ast


def test_bare_word_is_free_text():
    assert parse_query("serper") == {"field": "__text__", "op": "contains", "value": "serper"}


def test_text_prefix_free_text():
    assert parse_query('text: serper') == {"field": "__text__", "op": "contains", "value": "serper"}


def test_validate_filter_node_rejects_unknown_field():
    with pytest.raises(FilterValidationError):
        validate_filter_node({"field": "org_id", "op": "equals", "value": 1})


def test_validate_filter_node_rejects_bad_op_for_field():
    with pytest.raises(FilterValidationError):
        validate_filter_node({"field": "duration", "op": "contains", "value": 5})


def test_validate_filter_node_allows_flattened_dotted_path():
    validate_filter_node({"field": "details.tool", "op": "equals", "value": "Web Search Tool"})


def test_split_duration_filter_rejects_or():
    with pytest.raises(FilterValidationError):
        split_duration_filter(
            {
                "op": "or",
                "children": [
                    {"field": "status", "op": "equals", "value": "failed"},
                    {"field": "duration", "op": "gt", "value": 5},
                ],
            }
        )


def test_split_duration_filter_rejects_not():
    with pytest.raises(FilterValidationError):
        split_duration_filter({"op": "not", "child": {"field": "duration", "op": "gt", "value": 5}})


def test_split_duration_filter_combines_and_leaves():
    remainder, condition = split_duration_filter(
        {
            "op": "and",
            "children": [
                {"field": "status", "op": "equals", "value": "failed"},
                {"field": "duration", "op": "gt", "value": 10},
                {"field": "duration", "op": "lt", "value": 100},
            ],
        }
    )
    assert remainder == {"field": "status", "op": "equals", "value": "failed"}
    assert condition.matches(50)
    assert not condition.matches(5)
    assert not condition.matches(200)
