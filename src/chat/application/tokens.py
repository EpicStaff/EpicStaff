import hashlib
import re
import secrets

import jwt
from domain.errors import InvalidIdentityError

# The conversation.subject column width.
SUBJECT_MAX_LENGTH = 255
_UNSTORABLE_CHARACTER = re.compile("[\x00\ud800-\udfff]")


def issue_visitor_token() -> tuple[str, str]:
    """Return (token for the widget, sha256 hex stored on the conversation)."""
    token = secrets.token_urlsafe(32)
    return token, visitor_token_hash(token)


def visitor_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_callback_secret() -> str:
    # Django's serializer requires at least 32 characters; 32 bytes urlsafe is 43.
    return secrets.token_urlsafe(32)


def identity_subject(token: str | None, secret: str, *, now: int, max_lifetime_seconds: int) -> str:
    """The `sub` of a customer-issued HS256 token, or InvalidIdentityError."""
    if not token:
        raise InvalidIdentityError("identity_token is required on this binding.")
    try:
        claims = jwt.decode(
            token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError as error:
        raise InvalidIdentityError(str(error)) from error
    if int(claims["exp"]) - now > max_lifetime_seconds:
        raise InvalidIdentityError("identity_token may live at most one hour.")
    subject = str(claims["sub"])
    # Stored as conversation.subject: a text column cannot hold NUL, and psycopg cannot encode
    # a surrogate code point as UTF-8. PyJWT decodes the payload's bytes with json.loads, which
    # yields one for an unpaired "\ud800" escape and, decoding with "surrogatepass", two for a
    # pair sent as raw CESU-8 bytes. Refused rather than repaired: the subject identifies the
    # visitor, and a repaired one could equal another visitor's.
    if _UNSTORABLE_CHARACTER.search(subject):
        raise InvalidIdentityError(
            "identity_token sub may not contain NUL (U+0000) or a surrogate code point."
        )
    if len(subject) > SUBJECT_MAX_LENGTH:
        raise InvalidIdentityError(
            f"identity_token sub may be at most {SUBJECT_MAX_LENGTH} characters."
        )
    return subject
