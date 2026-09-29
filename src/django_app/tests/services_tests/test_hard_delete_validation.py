import pytest
from django.http import QueryDict

from rbac.exceptions import FormValidationError
from rbac.validation.hard_delete import HardDeleteValidationService


@pytest.fixture
def validator():
    return HardDeleteValidationService()


def test_returns_the_submitted_phrase_unchanged(validator):
    submitted = {"verification_phrase": " delete-A "}

    assert validator.extract_verification_phrase(submitted) == " delete-A "


@pytest.mark.parametrize("data", [{}, {"verification_phrase": None}, QueryDict("")])
def test_missing_phrase_is_none(validator, data):
    assert validator.extract_verification_phrase(data) is None


@pytest.mark.parametrize("data", [[], ["delete-A"], "delete-A", None])
def test_non_object_body_raises_on_the_phrase_field(validator, data):
    with pytest.raises(FormValidationError) as caught:
        validator.extract_verification_phrase(data)

    assert caught.value.errors[0]["field"] == "verification_phrase"


@pytest.mark.parametrize("value", [1, True, ["delete-a@x.com"], {"a": "delete-a@x.com"}])
def test_non_string_phrase_raises_with_the_value_redacted(validator, value):
    with pytest.raises(FormValidationError) as caught:
        validator.extract_verification_phrase({"verification_phrase": value})

    assert caught.value.errors == [
        {"field": "verification_phrase", "value": "***", "reason": "Must be a string."}
    ]
