from collections import OrderedDict

import pytest
from dotdict import DotDict

from src.shared.flow_templates import (
    PlaceholderKind,
    RefusedPlaceholderError,
    RenderedTemplate,
    inspect_template,
    render_template,
)

CANARY_NAME = "FLOW_TEMPLATES_TEST_CANARY"
CANARY_VALUE = "canary-from-the-crew-environment"
HIDDEN_VALUE = "value-that-must-not-reach-an-error"


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        ("Write about {topic}", {"topic": "cats"}, RenderedTemplate("Write about cats")),
        ("{a}{b}", {"a": 1, "b": None}, RenderedTemplate("1None")),
        ("Data {data}", {"data": {"k": [1, 2]}}, RenderedTemplate("Data {'k': [1, 2]}")),
        ("Id {user-id}", {"user-id": 7}, RenderedTemplate("Id 7")),
        ("Hi {first name}", {"first name": "Ann"}, RenderedTemplate("Hi Ann")),
        ("Hi {_private}", {"_private": "Ann"}, RenderedTemplate("Hi Ann")),
        (
            "{topic} and {missing} and {missing}",
            {"topic": "cats"},
            RenderedTemplate("cats and {missing} and {missing}", missing=("missing", "missing")),
        ),
        ('Esc {{"a": 1}} {{topic}} {topic}', {"topic": "cats"}, RenderedTemplate('Esc {"a": 1} {topic} cats')),
        ("No placeholders", {}, RenderedTemplate("No placeholders")),
        ("", {}, RenderedTemplate("")),
        ("Answer {context[user_input]}", {"context": {"user_input": "hi"}}, RenderedTemplate("Answer hi")),
        ("Answer {context.user_input}", {"context": {"user_input": "hi"}}, RenderedTemplate("Answer hi")),
        ("First {items[0]}", {"items": ["one", "two"]}, RenderedTemplate("First one")),
        ("Hi {data[first name]}", {"data": {"first name": "Ann"}}, RenderedTemplate("Hi Ann")),
        ("Deep {a[0][1].x}", {"a": [["skip", {"x": "found"}]]}, RenderedTemplate("Deep found")),
        ("Zero {d[0]}", {"d": {"0": "text key"}}, RenderedTemplate("Zero text key")),
        ("Nested {context[user]}", {"context": {"user": {"id": 1}}}, RenderedTemplate("Nested {'id': 1}")),
    ],
    ids=[
        "plain",
        "non-string-values",
        "structured-value",
        "hyphenated-name",
        "name-with-space",
        "underscore-plain-name",
        "missing-left-as-written",
        "escaped-braces",
        "no-placeholders",
        "empty",
        "bracket-key",
        "dotted-key",
        "list-index",
        "bracket-key-with-space",
        "mixed-index-and-key-chain",
        "digit-key-of-a-dict-is-text",
        "path-to-structured-value",
    ],
)
def test_placeholders_are_substituted(template, values, expected):
    assert render_template(template, values) == expected


@pytest.mark.parametrize(
    "placeholder",
    [
        "{context[absent]}",
        "{items[1]}",
        "{items[x]}",
        "{items[-1]}",
        "{items.0}",
        "{text.upper}",
        "{text[0]}",
        "{absent[key]}",
    ],
    ids=[
        "missing-key",
        "index-out-of-range",
        "text-key-into-a-list",
        "negative-index",
        "dotted-digit-into-a-list",
        "attribute-of-text",
        "index-into-text",
        "missing-head",
    ],
)
def test_path_that_does_not_resolve_is_left_as_written_and_reported(placeholder):
    values = {"context": {"user_input": "hi"}, "items": ["one"], "text": "cats"}

    rendered = render_template(f"Ask {{context[user_input]}} about {placeholder}", values)

    assert rendered == RenderedTemplate(f"Ask hi about {placeholder}", missing=(placeholder[1:-1],))


class ListSubclass(list):
    pass


@pytest.mark.parametrize(
    ("value", "placeholder"),
    [
        (DotDict({"k": "v"}), "{obj[k]}"),
        (DotDict({"k": "v"}), "{obj.k}"),
        (OrderedDict(k="v"), "{obj[k]}"),
        (ListSubclass(["v"]), "{obj[0]}"),
    ],
    ids=["dotdict-key", "dotdict-attribute", "ordered-dict", "list-subclass"],
)
def test_value_that_is_not_an_exact_dict_or_list_is_not_walked(value, placeholder):
    rendered = render_template(placeholder, {"obj": value})

    assert rendered == RenderedTemplate(placeholder, missing=(placeholder[1:-1],))


def test_getitem_of_a_value_is_never_called():
    class GetitemRecorder:
        def __init__(self):
            self.keys = []

        def __getitem__(self, key):
            self.keys.append(key)
            return "from __getitem__"

    recorder = GetitemRecorder()

    rendered = render_template("{obj[k]} {obj.k} {obj[0]}", {"obj": recorder})

    assert rendered.missing == ("obj[k]", "obj.k", "obj[0]")
    assert recorder.keys == []


@pytest.mark.parametrize(
    ("template", "refused_placeholder", "named"),
    [
        ("{a._b}", "{a._b}", "'_b'"),
        ("{_a.b}", "{_a.b}", "'_a'"),
        ("{a[_b]}", "{a[_b]}", "'_b'"),
        ("{a.__class__}", "{a.__class__}", "'__class__'"),
        ("{topic!r}", "{topic!r}", "'!r'"),
        ("{topic!s}", "{topic!s}", "'!s'"),
        ("{topic!a}", "{topic!a}", "'!a'"),
        ("{a[b]!r}", "{a[b]!r}", "'!r'"),
        ("{topic!r:>10}", "{topic!r:>10}", "'!r'"),
        ('{"a": 1} {x._y}', "{x._y}", "'_y'"),
        ("{0} {x._y}", "{x._y}", "'_y'"),
    ],
    ids=[
        "underscore-attribute",
        "underscore-head",
        "underscore-key",
        "dunder-attribute",
        "repr-conversion",
        "str-conversion",
        "ascii-conversion",
        "conversion-on-a-path",
        "conversion-with-spec",
        "refused-beats-json-example",
        "refused-beats-positional",
    ],
)
def test_refused_placeholder_raises_naming_only_the_placeholder(template, refused_placeholder, named):
    values = {
        "a": {"_b": HIDDEN_VALUE, "b": HIDDEN_VALUE},
        "_a": {"b": HIDDEN_VALUE},
        "topic": HIDDEN_VALUE,
        "x": {"_y": HIDDEN_VALUE},
    }

    with pytest.raises(RefusedPlaceholderError) as raised:
        render_template(f"Say {template}", values)

    message = str(raised.value)
    assert f"'{refused_placeholder}'" in message
    assert named in message
    assert HIDDEN_VALUE not in message
    assert raised.value.placeholder.field == refused_placeholder[1:-1]


@pytest.mark.parametrize(
    ("template", "expected_message"),
    [
        (
            "{context._x}",
            "Placeholder '{context._x}' is not allowed: '_x' starts with '_'. "
            "Rename that variable or key.",
        ),
        (
            "{topic!r}",
            "Placeholder '{topic!r}' is not allowed: conversions such as '!r' are not supported. "
            "Write '{topic}'.",
        ),
    ],
    ids=["underscore", "conversion"],
)
def test_refused_placeholder_message_tells_the_author_what_to_change(template, expected_message):
    with pytest.raises(RefusedPlaceholderError) as raised:
        render_template(template, {"context": {"_x": HIDDEN_VALUE}, "topic": HIDDEN_VALUE})

    assert str(raised.value) == expected_message


@pytest.mark.parametrize(
    "placeholder",
    [
        "{0}",
        "{}",
        "{.a}",
        "{[0]}",
        "{0[x]}",
        "{topic:>10}",
        "{a:{b}}",
        '{"label": "x"}',
        '{"a": {"b": 1}}',
        "{a..b}",
        "{a[b]c}",
        "{a[]}",
        '{"hi!": 1}',
        "{a!x}",
    ],
    ids=[
        "positional-index",
        "positional-auto",
        "attribute-of-nothing",
        "index-of-nothing",
        "path-from-a-positional",
        "format-spec",
        "nested-format-spec",
        "json-example",
        "nested-json-example",
        "empty-attribute",
        "text-after-a-key",
        "empty-key",
        "json-example-with-bang",
        "unknown-conversion",
    ],
)
def test_template_with_an_unrenderable_placeholder_is_returned_as_written(placeholder):
    template = f"Write about {{topic}} as {placeholder}"

    rendered = render_template(template, {"topic": "cats", "a": {"b": 1}, "b": 2})

    assert (rendered.text, rendered.missing) == (template, ())
    assert f"'{placeholder}'" in rendered.unrendered_reason


@pytest.mark.parametrize("template", ["Lone { brace {topic}", "Lone } brace {topic}"])
def test_template_that_does_not_parse_is_returned_as_written(template):
    rendered = render_template(template, {"topic": "cats"})

    # The reason is the parser's own message; only its presence is part of the contract.
    assert (rendered.text, rendered.missing) == (template, ())
    assert rendered.unrendered_reason


Kind = PlaceholderKind


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{topic}", [("topic", Kind.VALUE, True)]),
        ("{user-id}", [("user-id", Kind.VALUE, False)]),
        ("{context[user_input]}", [("context[user_input]", Kind.VALUE, True)]),
        ("{a[0].b}", [("a[0].b", Kind.VALUE, True)]),
        ("{0}", [("0", Kind.POSITIONAL, False)]),
        ("{.a}", [(".a", Kind.POSITIONAL, False)]),
        ("{topic!r}", [("topic!r", Kind.REFUSED, True)]),
        ("{a._b}", [("a._b", Kind.REFUSED, True)]),
        ('{"a": 1}', [('"a": 1', Kind.FORMATTED, False)]),
        ("{label: x}", [("label: x", Kind.FORMATTED, True)]),
        ('{"hi!": 1}', [('"hi!": 1', Kind.FORMATTED, False)]),
        ("{a..b}", [("a..b", Kind.BAD_PATH, True)]),
        ("{bad id[0]}", [("bad id[0]", Kind.VALUE, False)]),
        ("{topic} {0}", [("topic", Kind.VALUE, True), ("0", Kind.POSITIONAL, False)]),
        ("No placeholders {{x}}", []),
    ],
)
def test_inspect_template_classifies_each_placeholder(template, expected):
    inspection = inspect_template(template)

    assert inspection.parse_error is None
    assert [
        (placeholder.field, placeholder.kind, placeholder.variable_like)
        for placeholder in inspection.placeholders
    ] == expected
    for placeholder in inspection.placeholders:
        assert (placeholder.reason is None) == (placeholder.kind is PlaceholderKind.VALUE)


def test_inspect_template_reports_a_template_that_does_not_parse():
    inspection = inspect_template("Lone { brace {topic}")

    assert inspection.placeholders == ()
    assert inspection.parse_error


def test_attribute_chain_into_globals_does_not_reach_the_environment(monkeypatch):
    monkeypatch.setenv(CANARY_NAME, CANARY_VALUE)
    template = "{obj.update.__globals__[ast].sys.modules[os].environ[" + CANARY_NAME + "]}"

    with pytest.raises(RefusedPlaceholderError) as raised:
        render_template(f"Classify {template}", {"obj": DotDict({"k": "v"})})

    assert CANARY_VALUE not in str(raised.value)
