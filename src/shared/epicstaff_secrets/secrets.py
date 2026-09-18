from __future__ import annotations

import json
import os

ENV_VAR = "EPICSTAFF_SECRETS"


class SecretNotAvailableError(RuntimeError):
    """Raised when the requested secret was not declared for this node.

    Deliberately not a KeyError: the sandbox wrapper prints str(e) to stderr,
    and KeyError's str() wraps the message in quotes.
    """


__cache: dict[str, dict[str, str]] = {}


def _load() -> dict[str, str]:
    if "secrets" not in __cache:
        raw = os.environ.get(ENV_VAR)
        __cache["secrets"] = json.loads(raw) if raw else {}
    return __cache["secrets"]


def clear_cache() -> None:
    """Drop the parsed payload. For tests; a real execution is a fresh process."""
    __cache.clear()


def get_secret(name: str) -> str:
    """Return the plaintext of a secret this node declared.

    Raises SecretNotAvailableError if `name` was not declared for this node.
    There is deliberately no `default=` parameter: a silently-None credential
    fails later and more confusingly than an immediate exception.
    """
    available = _load()
    if name not in available:
        declared = ", ".join(sorted(available)) or "none"
        raise SecretNotAvailableError(
            f"Secret '{name}' was not declared for this node. "
            f"Declared secrets: {declared}. "
            f"Add it to this node's secrets to make it readable."
        )
    return available[name]
