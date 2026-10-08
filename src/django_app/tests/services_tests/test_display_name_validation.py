import pytest

from rbac.exceptions import FormValidationError
from rbac.validation.auth import AuthValidationService
from rbac.validation.base import REDACTED_PLACEHOLDER, BaseRBACValidator
from rbac.validation.user import UserValidationService

CREDENTIALS = {"email": "jane@example.com", "password": "StrongPass123!"}

CREATION_BLANK_REASON = "Must not be blank. Omit it or use null to derive it from the email."

INVALID_CREATION_DISPLAY_NAMES = [
    ("", CREATION_BLANK_REASON),
    ("   ", CREATION_BLANK_REASON),
    ("x" * 256, "Must be 255 characters or fewer."),
    (123, "Must be a string or null."),
    (["Jane"], "Must be a string or null."),
]


@pytest.fixture
def auth_validator():
    return AuthValidationService()


@pytest.fixture
def user_validator():
    return UserValidationService()


# ---- creation endpoints: first setup / reset user / admin create ----


@pytest.fixture(
    params=["first_setup", "reset_user", "create_user"],
)
def validate_creation(request, auth_validator, user_validator):
    return {
        "first_setup": auth_validator.validate_first_setup,
        "reset_user": auth_validator.validate_reset_user,
        "create_user": user_validator.validate_create_user,
    }[request.param]


@pytest.mark.parametrize("body", [CREDENTIALS, {**CREDENTIALS, "display_name": None}])
def test_creation_missing_or_null_display_name_is_none(validate_creation, body):
    assert validate_creation(body)["display_name"] is None


@pytest.mark.parametrize(
    ("submitted", "cleaned"),
    [("  Jane Doe  ", "Jane Doe"), ("x" * 255, "x" * 255), ("  " + "x" * 255 + " ", "x" * 255)],
    ids=["trimmed", "max-length", "max-length-after-trim"],
)
def test_creation_display_name_is_trimmed(validate_creation, submitted, cleaned):
    assert validate_creation({**CREDENTIALS, "display_name": submitted})["display_name"] == cleaned


@pytest.mark.parametrize(("submitted", "reason"), INVALID_CREATION_DISPLAY_NAMES)
def test_creation_rejects_invalid_display_name(validate_creation, submitted, reason):
    with pytest.raises(FormValidationError) as caught:
        validate_creation({**CREDENTIALS, "display_name": submitted})

    assert caught.value.errors == [
        {"field": "display_name", "value": submitted, "reason": reason}
    ]


def test_creation_aggregates_display_name_with_email_errors(validate_creation):
    with pytest.raises(FormValidationError) as caught:
        validate_creation(
            {"email": "not-an-email", "password": "StrongPass123!", "display_name": "  "}
        )

    fields = [error["field"] for error in caught.value.errors]
    assert "email" in fields
    assert "display_name" in fields


# ---- profile PATCH keeps its own contract ----


@pytest.mark.parametrize(
    ("submitted", "reason"),
    [
        ("", "Must not be blank. Use null to clear."),
        ("   ", "Must not be blank. Use null to clear."),
        ("x" * 256, "Must be 255 characters or fewer."),
        (42, "Must be a string or null."),
    ],
)
def test_profile_patch_rejects_invalid_display_name(user_validator, submitted, reason):
    with pytest.raises(FormValidationError) as caught:
        user_validator.validate_profile_patch({"display_name": submitted})

    assert caught.value.errors == [
        {"field": "display_name", "value": submitted, "reason": reason}
    ]


def test_profile_patch_null_clears_display_name(user_validator):
    assert user_validator.validate_profile_patch({"display_name": None}) == {"display_name": None}


def test_profile_patch_trims_display_name(user_validator):
    assert user_validator.validate_profile_patch({"display_name": "  Padded  "}) == {
        "display_name": "Padded"
    }


def test_profile_patch_without_display_name_returns_nothing(user_validator):
    assert user_validator.validate_profile_patch({}) == {}


# ---- redaction ----


class _RedactingDisplayNameValidator(BaseRBACValidator):
    _redacted_fields = frozenset({"display_name"})


def test_display_name_error_value_follows_redaction():
    _, errors = _RedactingDisplayNameValidator()._clean_display_name("   ")

    assert errors[0].value == REDACTED_PLACEHOLDER
