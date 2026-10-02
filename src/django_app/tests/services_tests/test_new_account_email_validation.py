import pytest

from rbac.exceptions import FormValidationError
from rbac.validation.auth import AuthValidationService
from rbac.validation.user import UserValidationService

PASSWORD = "StrongPass123!"

EDGE_REASON = "The part before @ must start and end with a letter or digit."
FORMAT_REASON = "Enter a valid email address."
CHARACTERS_REASON = "Use only letters, digits and . _ - + before the @."
LENGTH_REASON = "Must be at most 254 characters, with at most 64 before the @."

ACCEPTED_EMAILS = [
    "john.smith@gmail.com",
    "john_smith@gmail.com",
    "john-smith@gmail.com",
    "JOHN.SMITH@gmail.com",
    "john+newsletter@gmail.com",
    "john.1990.smith@gmail.com",
    "12345@gmail.com",
    "j.r.r.tolkien@gmail.com",
    "a@b.co",
    "anna@mail.company.com.ua",
    "x" * 64 + "@gmail.com",
]

REJECTED_EMAILS = [
    ("---@gmail.com", EDGE_REASON),
    ("___@gmail.com", EDGE_REASON),
    ("+john@gmail.com", EDGE_REASON),
    ("__proto__@hys-enterprise.com", EDGE_REASON),
    ("---@localhost", EDGE_REASON),
    ("john smith@gmail.com", "Email must not contain whitespace."),
    ("aaaa!@x.com", CHARACTERS_REASON),
    ("john%smith@gmail.com", CHARACTERS_REASON),
    ("john!#$&*smith@gmail.com", CHARACTERS_REASON),
    ("o'brien@gmail.com", CHARACTERS_REASON),
    ('"john"@gmail.com', CHARACTERS_REASON),
    ("john@localhost", FORMAT_REASON),
    ("john@gmail.c0m", FORMAT_REASON),
    ("x" * 65 + "@gmail.com", LENGTH_REASON),
    ("x" * 64 + "@" + "d" * 63 + "." + "d" * 63 + "." + "d" * 63 + ".com", LENGTH_REASON),
    # Kelvin sign: Django's case-insensitive regex lets it through as "K".
    ("Kate@x.com", CHARACTERS_REASON),
    ("john@bücher.de", FORMAT_REASON),
]


@pytest.fixture(params=["first_setup", "reset_user", "create_user"])
def validate_creation(request):
    return {
        "first_setup": AuthValidationService().validate_first_setup,
        "reset_user": AuthValidationService().validate_reset_user,
        "create_user": UserValidationService().validate_create_user,
    }[request.param]


@pytest.mark.parametrize("email", ACCEPTED_EMAILS)
def test_creation_accepts_common_email(validate_creation, email):
    assert validate_creation({"email": email, "password": PASSWORD})["email"] == email


@pytest.mark.parametrize(("email", "reason"), REJECTED_EMAILS)
def test_creation_rejects_unusual_email(validate_creation, email, reason):
    with pytest.raises(FormValidationError) as caught:
        validate_creation({"email": email, "password": PASSWORD})

    assert {"field": "email", "value": email, "reason": reason} in caught.value.errors


def test_creation_still_rejects_what_the_rfc_check_rejects(validate_creation):
    with pytest.raises(FormValidationError) as caught:
        validate_creation({"email": "john..smith@gmail.com", "password": PASSWORD})

    assert caught.value.errors == [
        {"field": "email", "value": "john..smith@gmail.com", "reason": FORMAT_REASON}
    ]


@pytest.mark.parametrize("email", ["---@gmail.com", "__proto__@hys-enterprise.com"])
def test_password_reset_request_keeps_accepting_existing_unusual_emails(email):
    assert AuthValidationService().validate_password_reset_request({"email": email}) == {
        "email": email
    }


def test_add_member_by_email_keeps_accepting_existing_unusual_emails():
    cleaned = UserValidationService().validate_add_member(
        {"org_id": 1, "role_id": 3, "email": "---@gmail.com"}
    )

    assert cleaned["email"] == "---@gmail.com"
