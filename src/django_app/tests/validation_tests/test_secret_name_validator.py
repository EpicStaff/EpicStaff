import pytest
from django.core.exceptions import ValidationError

from tables.validators.secret_name_validator import validate_secret_name


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_KEY",
        "my-key 2",
        "Ключ",
        "release.v2",
        "Ключ_2 prod-key.v1",
        "système",
        "²",  # a Unicode number that is not an ASCII digit
    ],
)
def test_accepts_letters_digits_space_underscore_dash_and_dot(name):
    validate_secret_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "a(b",
        "a)b",
        "a{b",
        "a}b",
        "a+b",
        'a"b',
        "a'b",
        r"a\b",
        "a<b",
        "a:b",
        "a/b",
        "a\nb",
        "a\tb",
        "a\x00b",
        "",
        "a·b",
        "á",
    ],
    ids=[
        "open-paren",
        "close-paren",
        "open-brace",
        "close-brace",
        "plus",
        "double-quote",
        "single-quote",
        "backslash",
        "lt",
        "colon",
        "slash",
        "newline",
        "tab",
        "nul",
        "empty",
        "middle-dot",
        "combining-mark",
    ],
)
def test_rejects_any_other_character(name):
    with pytest.raises(ValidationError) as error:
        validate_secret_name(name)

    assert error.value.code == "invalid_secret_name"
    assert error.value.message == (
        "Secret name may contain only letters, digits, spaces, and _ - . characters."
    )
