"""Keep credentials out of logs, assertion messages and tracebacks.

Three layers:
- `redact(value)` replaces values whose key looks like a credential (by lower-cased
  substring) in JSON-like data.
- A registry of known secrets: whatever the suite creates (API key, JWTs, passwords, SSE
  tickets) is registered, and `scrub(text)` replaces every occurrence in free text.
- `Secret`, a `str` whose `repr` is redacted, so `--showlocals` and pytest's saferepr can't
  print a credential held in a variable. `str()` and f-strings still give the raw value.
"""

import re
import threading

REDACTED = "<redacted>"
SECRET_KEY_PARTS = ("password", "token", "secret", "api_key", "ticket", "access", "refresh")
SECRET_QUERY_PATTERN = re.compile(
    r"([?&][^=&#]*(?:password|token|secret|api_key|ticket|access|refresh)[^=&#]*=)[^&#]+",
    re.IGNORECASE,
)
# Shorter values would scrub ordinary words out of the output.
MINIMUM_SECRET_LENGTH = 8


class Secret(str):
    """A credential: behaves as its raw string, but `repr` never shows it."""

    def __repr__(self) -> str:
        return REDACTED


_known_secrets: set[str] = set()
_known_secrets_lock = threading.Lock()


def register_secret(value: str) -> Secret:
    """Remember a credential so `scrub` removes it from any text; return it as a `Secret`."""
    raw = str(value)
    if len(raw) >= MINIMUM_SECRET_LENGTH:
        with _known_secrets_lock:
            _known_secrets.add(raw)
    return Secret(raw)


def scrub(text: str) -> str:
    """Replace every registered secret in `text`, longest first."""
    with _known_secrets_lock:
        known = sorted(_known_secrets, key=len, reverse=True)
    for secret in known:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def is_secret_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SECRET_KEY_PARTS)


def redact(value: object) -> object:
    """Copy JSON-like data with credential-keyed values replaced and strings scrubbed.

    Only string values are replaced: credentials are strings, while keys such as the
    `secrets` resource in a permission map hold lists and ids that are not secret.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if is_secret_key(key) and isinstance(item, str) and item else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return scrub(value)
    return value


def protect(value: object) -> object:
    """Copy JSON-like data with credential-keyed strings registered and wrapped in `Secret`.

    Unlike `redact`, the values stay usable; only their `repr` hides them.
    """
    if isinstance(value, dict):
        return {
            key: register_secret(item)
            if is_secret_key(key) and isinstance(item, str) and item
            else protect(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [protect(item) for item in value]
    return value


def redact_url(url: str) -> str:
    return scrub(SECRET_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}{REDACTED}", url))
