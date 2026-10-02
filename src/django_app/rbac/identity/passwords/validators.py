import re

from django.core.exceptions import ValidationError


class PrintableAsciiPasswordValidator:
    """
    Restrict password alphabet to printable ASCII excluding whitespace
    (bytes 0x21-0x7E): Latin letters, digits, and standard ASCII
    symbols. Rejects whitespace, control characters, and any non-ASCII
    codepoint.
    """

    PATTERN = re.compile(r"^[\x21-\x7E]+$")
    HELP_TEXT = (
        "Your password may contain only Latin letters (A-Z, a-z), "
        "digits (0-9), and standard ASCII symbols "
        "(!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~). "
        "Whitespace and non-ASCII characters are not allowed."
    )

    def validate(self, password, user=None):
        if not password or not self.PATTERN.fullmatch(password):
            raise ValidationError(
                "Password may contain only Latin letters, digits, and "
                "standard ASCII symbols; whitespace and non-ASCII "
                "characters are not allowed.",
                code="password_invalid_characters",
            )

    def get_help_text(self):
        return self.HELP_TEXT
