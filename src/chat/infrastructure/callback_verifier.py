"""Receiver side of EpicStaff's src/django_app/tables/services/session_callbacks/signing.py; the fixture under tests/contracts pins both."""

import hashlib
import hmac

from domain.errors import CallbackRejectedError

SIGNATURE_HEADER = "X-EpicStaff-Signature"
TIMESTAMP_HEADER = "X-EpicStaff-Timestamp"
SESSION_ID_HEADER = "X-EpicStaff-Session-Id"
PREFIX = "sha256="


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256
    ).hexdigest()
    return PREFIX + digest


def verify(
    secret: str,
    timestamp: str | None,
    body: bytes,
    signature: str | None,
    *,
    now: int,
    max_skew_seconds: int,
) -> None:
    """Raise CallbackRejectedError unless the signature matches and the timestamp is within the skew window."""
    if not timestamp or not signature or not signature.startswith(PREFIX):
        raise CallbackRejectedError("Missing signature or timestamp.")
    try:
        sent_at = int(timestamp)
    except ValueError as error:
        raise CallbackRejectedError("Timestamp is not an integer.") from error
    if abs(now - sent_at) > max_skew_seconds:
        raise CallbackRejectedError("Timestamp outside the accepted window.")
    # compare_digest raises TypeError on a non-ASCII str instead of returning False.
    if not signature.isascii():
        raise CallbackRejectedError("Signature mismatch.")
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise CallbackRejectedError("Signature mismatch.")
