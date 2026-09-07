import re

TELEGRAM_SECRET_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def validate_telegram_secret_token(value: str) -> None:
    """Raises `ValueError` if `value` cannot be used as a Telegram
    `secret_token` (see `TELEGRAM_SECRET_TOKEN_RE`)."""
    if not value or not TELEGRAM_SECRET_TOKEN_RE.fullmatch(value):
        raise ValueError(
            "Telegram secret_token must be 1-256 characters using only "
            "letters, digits, underscores, and hyphens (A-Z, a-z, 0-9, '_', "
            "'-') -- this is a constraint from Telegram's own Bot API, not "
            "EpicStaff's."
        )
