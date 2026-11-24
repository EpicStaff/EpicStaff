from typing import Literal

import pytest
from ai_models.domain.value_types import ValueTypeRegistry
from jsonschema import Draft202012Validator

from tests.ai_models_tests.factories import make_model, make_parameter


def _accepts(fragment: dict, value) -> bool:
    return Draft202012Validator(fragment).is_valid(value)


def test_number_fragment_uses_model_limit_over_registry_maximum():
    spec = make_parameter(
        "max_tokens",
        value_type="integer",
        control="stepper",
        default=4096,
        minimum=1,
        maximum=None,
        limit_from="max_output_tokens",
    )
    model = make_model(limits={"max_output_tokens": 16384})

    fragment = ValueTypeRegistry().get("integer").schema_fragment(spec, model)

    assert fragment["type"] == "integer" and fragment["minimum"] == 1
    assert fragment["maximum"] == 16384
    assert fragment["x-widget"] == "stepper"


def test_limit_falls_back_to_registry_maximum_when_model_lacks_it():
    spec = make_parameter(
        "max_tokens",
        value_type="integer",
        control="stepper",
        default=4096,
        minimum=500,
        maximum=100000,
        limit_from="max_output_tokens",
    )

    for model in (None, make_model(limits={})):
        fragment = ValueTypeRegistry().get("integer").schema_fragment(spec, model)
        assert fragment["maximum"] == 100000


@pytest.mark.parametrize(
    ("value", "accepted"),
    [(-0.01, False), (0, True), (2, True), (2.01, False), (None, False), ("1", False)],
)
def test_number_range_is_enforced_on_both_sides(value, accepted):
    spec = make_parameter("temperature", default=0.7, minimum=0, maximum=2)

    fragment = ValueTypeRegistry().get("number").schema_fragment(spec, None)

    assert _accepts(fragment, value) is accepted


@pytest.mark.parametrize(
    ("value", "accepted"), [(499, False), (500, True), (16384, True), (16385, False), (1.5, False)]
)
def test_integer_limit_from_model_is_enforced_on_both_sides(value, accepted):
    spec = make_parameter(
        "max_tokens",
        value_type="integer",
        control="stepper",
        default=4096,
        minimum=500,
        limit_from="max_output_tokens",
    )
    model = make_model(limits={"max_output_tokens": 16384})

    fragment = ValueTypeRegistry().get("integer").schema_fragment(spec, model)

    assert _accepts(fragment, value) is accepted


def test_percent_number_carries_scale_hint():
    spec = make_parameter(
        "top_p", value_type="number", control="percent", minimum=0.01, maximum=1.0
    )

    fragment = ValueTypeRegistry().get("number").schema_fragment(spec, None)

    assert fragment["x-widget"] == "percent" and fragment["x-scale"] == 100


@pytest.mark.parametrize(
    ("value_type", "step"), [("number", 0.01), ("integer", 100)]
)
def test_numeric_fragment_carries_step_hint(value_type, step):
    spec = make_parameter("setting", value_type=value_type, minimum=0, maximum=1000, step=step)

    fragment = ValueTypeRegistry().get(value_type).schema_fragment(spec, None)

    assert fragment["x-step"] == step
    assert "multipleOf" not in fragment


def test_no_step_hint_without_a_step():
    spec = make_parameter("setting", minimum=0, maximum=2, step=None)

    assert "x-step" not in ValueTypeRegistry().get("number").schema_fragment(spec, None)


def test_scale_hint_only_on_percent():
    spec = make_parameter("temperature", control="slider", minimum=0, maximum=2)

    fragment = ValueTypeRegistry().get("number").schema_fragment(spec, None)

    assert "x-scale" not in fragment


def test_fragment_carries_ui_text_default_and_group():
    spec = make_parameter(
        "temperature",
        label="Temperature",
        help_text="Controls randomness.",
        group="sampling",
        default=0.7,
        minimum=0,
        maximum=2,
    )

    fragment = ValueTypeRegistry().get("number").schema_fragment(spec, None)

    assert fragment["title"] == "Temperature"
    assert fragment["description"] == "Controls randomness."
    assert fragment["default"] == 0.7
    assert fragment["x-group"] == "sampling"


def test_choice_fragment_prefers_model_options():
    spec = make_parameter(
        "reasoning_effort",
        value_type="choice",
        control="select",
        default="low",
        options=("low", "medium", "high"),
    )
    model = make_model(options={"reasoning_effort": ("low", "high")})

    assert ValueTypeRegistry().get("choice").schema_fragment(spec, model)["enum"] == ["low", "high"]


def test_choice_fragment_uses_registry_options_without_model_options():
    spec = make_parameter(
        "reasoning_effort",
        value_type="choice",
        control="select",
        default="low",
        options=("low", "medium", "high"),
    )

    fragment = ValueTypeRegistry().get("choice").schema_fragment(spec, make_model())

    assert fragment["enum"] == ["low", "medium", "high"]


@pytest.mark.parametrize(
    ("value_type", "control", "options", "set_value"),
    [
        ("number", "slider", (), 1.5),
        ("integer", "stepper", (), 7),
        ("boolean", "toggle", (), True),
        ("choice", "select", ("low", "high"), "low"),
        ("text", "text", (), "abc"),
        ("text_list", "chips", (), ["a", "b"]),
        ("json", "json", (), {"1": 2.0}),
    ],
)
def test_not_set_default_accepts_null_and_a_set_value(value_type, control, options, set_value):
    spec = make_parameter("setting", value_type=value_type, control=control, options=options)

    fragment = ValueTypeRegistry().get(value_type).schema_fragment(spec, None)

    assert fragment["default"] is None
    assert _accepts(fragment, None)
    assert _accepts(fragment, set_value)


def test_choice_rejects_value_outside_model_options():
    spec = make_parameter(
        "reasoning_effort", value_type="choice", control="select", options=("low", "medium", "high")
    )
    model = make_model(options={"reasoning_effort": ("low", "high")})

    fragment = ValueTypeRegistry().get("choice").schema_fragment(spec, model)

    assert not _accepts(fragment, "medium")


@pytest.mark.parametrize(("limit", "default"), [(1024, 1024), (4096, 4096), (16384, 4096)])
def test_numeric_default_never_exceeds_the_model_limit(limit, default):
    spec = make_parameter(
        "max_tokens",
        value_type="integer",
        control="stepper",
        default=4096,
        minimum=1,
        limit_from="max_output_tokens",
    )
    model = make_model(limits={"max_output_tokens": limit})

    fragment = ValueTypeRegistry().get("integer").schema_fragment(spec, model)

    assert fragment["default"] == default
    assert _accepts(fragment, fragment["default"])


def test_choice_default_the_model_does_not_offer_is_not_set():
    spec = make_parameter(
        "reasoning_effort",
        value_type="choice",
        control="select",
        default="medium",
        options=("low", "medium", "high"),
    )
    model = make_model(options={"reasoning_effort": ("low", "high")})

    fragment = ValueTypeRegistry().get("choice").schema_fragment(spec, model)

    assert fragment["default"] is None
    assert _accepts(fragment, None) and _accepts(fragment, "low")
    assert not _accepts(fragment, "medium")


def test_set_default_rejects_null():
    spec = make_parameter("logprobs", value_type="boolean", control="toggle", default=False)

    fragment = ValueTypeRegistry().get("boolean").schema_fragment(spec, None)

    assert not _accepts(fragment, None)


@pytest.mark.parametrize(
    ("value", "accepted"), [(["END", "STOP"], True), ([], True), ([1], False), ("END", False)]
)
def test_text_list_accepts_only_lists_of_strings(value, accepted):
    spec = make_parameter("stop", value_type="text_list", control="chips", default=[])

    fragment = ValueTypeRegistry().get("text_list").schema_fragment(spec, None)

    assert _accepts(fragment, value) is accepted


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (bool | None, "boolean"),
        (int | None, "integer"),
        (float | None, "number"),
        (list[str] | None, "text_list"),
        (dict | None, "json"),
        (dict[int, float] | None, "json"),
        (str | None, "text"),
        (Literal["low", "high"] | None, "choice"),
        (str | list[str] | None, "json"),
        (object, "json"),
    ],
)
def test_guess_maps_annotations(annotation, expected):
    assert ValueTypeRegistry().guess(annotation).name == expected


def test_get_rejects_unknown_value_type():
    with pytest.raises(ValueError, match="decimal"):
        ValueTypeRegistry().get("decimal")
