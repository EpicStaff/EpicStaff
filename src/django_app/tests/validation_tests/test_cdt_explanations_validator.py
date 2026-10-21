"""The storage rules for a CDT node's `metadata["explanations"]`, tested directly."""

from unittest import mock

import pytest
from rest_framework import serializers
from rest_framework.settings import api_settings

from tables.constants.cdt_explanation_limits import MAX_STEP_KEY_LENGTH, MAX_STORED_EXPLANATIONS
from tables.validators import cdt_explanations
from tables.validators.cdt_explanations import MAX_EXAMINED_KEYS, review_explanations

# Nothing here queries the ORM, but tests/conftest.py's autouse `heal_builtin_roles`
# does before every database test; without the `db` fixture it would query the
# real dev database instead of the test one.
pytestmark = pytest.mark.django_db


def _explanation(text="Checks the score."):
    return {"text": text, "generatedBy": "gpt-4o-mini", "fingerprint": "fp-1"}


def test_a_valid_map_at_the_count_limit_is_kept_whole():
    explanations = {f"step-{index}": _explanation() for index in range(MAX_STORED_EXPLANATIONS)}

    review = review_explanations(explanations)

    assert review.kept == explanations
    assert (review.malformed, review.over_limit) == (0, 0)


def test_a_huge_malformed_map_is_examined_only_up_to_the_bound():
    valid = {f"a-{index}": _explanation() for index in range(10)}
    malformed = {f"k-{index}": "not an object" for index in range(50_000)}

    with (
        mock.patch.object(
            cdt_explanations, "_clean_entry", wraps=cdt_explanations._clean_entry
        ) as clean_entry,
        mock.patch.object(
            serializers.Serializer, "__init__", side_effect=AssertionError("serializer built")
        ),
    ):
        review = review_explanations({**malformed, **valid})

    assert review.kept == valid
    assert clean_entry.call_count == MAX_EXAMINED_KEYS
    assert review.malformed == MAX_EXAMINED_KEYS - len(valid)
    assert review.over_limit == len(malformed) + len(valid) - MAX_EXAMINED_KEYS
    assert review.errors is None


def test_reasons_are_kept_only_when_asked_for():
    explanations = {"bad": "not an object", "ok": _explanation()}

    counted = review_explanations(explanations)
    explained = review_explanations(explanations, collect_errors=True)

    assert counted.errors is None
    assert counted.malformed == explained.malformed == 1
    assert explained.errors == {"bad": ["Each explanation must be an object."]}
    assert counted.kept == explained.kept == {"ok": _explanation()}


@pytest.mark.parametrize(
    "step_key",
    [
        pytest.param("", id="empty"),
        pytest.param("k" * (MAX_STEP_KEY_LENGTH + 1), id="too-long"),
        pytest.param("rule:a\x00b", id="nul"),
        pytest.param("rule:\ud800", id="surrogate"),
    ],
)
def test_an_unstorable_step_key_is_dropped_without_echoing_it(step_key):
    review = review_explanations({step_key: _explanation(), "ok": _explanation()}, collect_errors=True)

    assert review.kept == {"ok": _explanation()}
    assert review.malformed == 1
    assert list(review.errors) == [api_settings.NON_FIELD_ERRORS_KEY]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("text", "a\x00b", id="nul-in-text"),
        pytest.param("generatedBy", "\ud800", id="surrogate-in-generated-by"),
        pytest.param("fingerprint", "fp\udfff", id="surrogate-in-fingerprint"),
    ],
)
def test_null_and_surrogate_characters_make_an_entry_malformed(field_name, value):
    review = review_explanations({"k": {**_explanation(), field_name: value}}, collect_errors=True)

    assert review.kept == {}
    assert review.errors == {"k": {field_name: ["Null and surrogate characters are not allowed."]}}
