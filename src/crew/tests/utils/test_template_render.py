import pytest
from dotdict import DotDict

from utils.template_render import RenderedTemplate, render_template

CANARY_NAME = "TEMPLATE_RENDER_TEST_CANARY"
CANARY_VALUE = "canary-from-the-crew-environment"


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        ("Write about {topic}", {"topic": "cats"}, RenderedTemplate("Write about cats")),
        ("{a}{b}", {"a": 1, "b": None}, RenderedTemplate("1None")),
        ("Data {data}", {"data": {"k": [1, 2]}}, RenderedTemplate("Data {'k': [1, 2]}")),
        ("Id {user-id}", {"user-id": 7}, RenderedTemplate("Id 7")),
        (
            "{topic} and {missing} and {missing}",
            {"topic": "cats"},
            RenderedTemplate("cats and {missing} and {missing}", missing=("missing", "missing")),
        ),
        ('Esc {{"a": 1}} {{topic}} {topic}', {"topic": "cats"}, RenderedTemplate('Esc {"a": 1} {topic} cats')),
        ("No placeholders", {}, RenderedTemplate("No placeholders")),
        ("", {}, RenderedTemplate("")),
    ],
    ids=[
        "plain",
        "non-string-values",
        "structured-value",
        "hyphenated-name",
        "missing-left-as-written",
        "escaped-braces",
        "no-placeholders",
        "empty",
    ],
)
def test_plain_placeholders_are_substituted(template, values, expected):
    assert render_template(template, values) == expected


@pytest.mark.parametrize(
    ("template", "expected_reason"),
    [
        ("Name {user.name}", "placeholder 'user.name' is not a plain variable name"),
        ("First {items[0]}", "placeholder 'items[0]' is not a plain variable name"),
        ("Key {user[name]}", "placeholder 'user[name]' is not a plain variable name"),
        ("Positional {0}", "placeholder '0' is not a plain variable name"),
        ("Auto {}", "placeholder '' is not a plain variable name"),
        ("Repr {topic!r}", "placeholder 'topic' uses a conversion or format spec"),
        ("Padded {topic:>10}", "placeholder 'topic' uses a conversion or format spec"),
        ("Nested spec {a:{b}}", "placeholder 'a' uses a conversion or format spec"),
        ('Answer {topic} as {"label": "x"}', "placeholder '\"label\"' uses a conversion or format spec"),
        ('Nested {"a": {"b": 1}} {topic}', "placeholder '\"a\"' uses a conversion or format spec"),
    ],
)
def test_template_with_anything_but_plain_placeholders_is_returned_as_written(
    template, expected_reason
):
    values = {"user": {"name": "Ann"}, "items": ["first"], "topic": "cats", "a": 1, "b": 10}

    rendered = render_template(template, values)

    assert rendered == RenderedTemplate(template, unrendered_reason=expected_reason)


@pytest.mark.parametrize("template", ["Lone { brace {topic}", "Lone } brace {topic}"])
def test_template_that_does_not_parse_is_returned_as_written(template):
    rendered = render_template(template, {"topic": "cats"})

    # The reason is the parser's own message; only its presence is part of the contract.
    assert (rendered.text, rendered.missing) == (template, ())
    assert rendered.unrendered_reason


@pytest.mark.parametrize(
    "value",
    [DotDict({"k": "v"}), {"k": "v"}],
    ids=["live-dotdict", "plain-dict"],
)
def test_attribute_chain_into_globals_does_not_reach_the_environment(monkeypatch, value):
    monkeypatch.setenv(CANARY_NAME, CANARY_VALUE)
    template = "{obj.update.__globals__[ast].sys.modules[os].environ[" + CANARY_NAME + "]}"

    rendered = render_template(f"Classify {template}", {"obj": value})

    assert rendered.text == f"Classify {template}"
    assert CANARY_VALUE not in rendered.text
