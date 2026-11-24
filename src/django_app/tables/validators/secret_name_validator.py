from django.core.exceptions import ValidationError

ALLOWED_SECRET_NAME_PUNCTUATION = frozenset(" _-.")


def validate_secret_name(value: str) -> None:
    """Accept only names made of letters, digits, spaces and `_ - .`.

    The code editor inserts a secret's name into `get_secret("<name>")` in a colleague's
    Python code, and the cursor may already sit inside a string or an f-string there. A
    blocklist of quotes and backslashes is not enough: inside an f-string `{ }` start an
    expression, and `( ) +` and other operators become code once a quote is closed. An
    allowlist leaves no character that can close a literal, open an expression or call
    anything. Letters and digits are any Unicode ones (`str.isalnum()`); the frontend
    applies the same rule as `/^[\\p{L}\\p{N} _.-]+$/u`, so keep the two identical.
    """
    if not value or not all(
        character.isalnum() or character in ALLOWED_SECRET_NAME_PUNCTUATION for character in value
    ):
        raise ValidationError(
            "Secret name may contain only letters, digits, spaces, and _ - . characters.",
            code="invalid_secret_name",
        )
