"""Logging helpers — redact secrets before dumping request/config/messages to logs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import secrets
from typing import Any

_DIGEST_CHARS = 12

# The key is generated per process and never leaves it.
_DIGEST_KEY = secrets.token_bytes(32)

_SENSITIVE = (
    "api_key",
    "access_key",
    "secret_key",
    "auth",
    "authorization",
    "headers",
    "extra_headers",
    "password",
    "token",
    "secret",
)


def redact(value):
    """Mask dict values whose key is in `_SENSITIVE`, recursing into dicts and lists.

    Masking is by key name only. A scalar passed in directly — a string, a number — is
    returned unchanged, as is a secret stored under a key this module does not know
    about.

    Returns a new structure; tuples come back as lists.
    """
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE and v is not None else redact(v))
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]

    return value


def redact_value(value) -> str:
    """Replace a value with its length and a keyed digest of its content.

    Any non-string value is stringified first, so no input type can fall through and
    reach the log verbatim. `None` becomes `<none>`; everything else becomes
    `<redacted len=N digest=XXXXXXXXXXXX>`. Within one process the digest is stable, so
    two log lines can be compared for equal content without revealing it.
    """
    if value is None:
        return "<none>"

    text = str(value)
    digest = hmac.new(_DIGEST_KEY, text.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"<redacted len={len(text)} digest={digest[:_DIGEST_CHARS]}>"


_MESSAGE_PASSTHROUGH_KEYS = {"role", "tool_call_id", "name"}
_TOOL_CALL_PASSTHROUGH_KEYS = {"id", "type"}
_TOOL_CALL_KEY = "tool_calls"
_FUNCTION_KEY = "function"
_FUNCTION_PASSTHROUGH_KEYS = {"name"}
_TOOL_CALL_STRUCTURAL_KEYS = _TOOL_CALL_PASSTHROUGH_KEYS | {_FUNCTION_KEY}


def redact_messages(messages: list[Any]) -> list[dict | str]:
    """Redact a chat message list for logging: digest every field by default.

    Only `_MESSAGE_PASSTHROUGH_KEYS` pass through unchanged; everything else —
    including a key this module has never seen — is replaced by a `redact_value`
    digest, except `tool_calls`, which `_redact_tool_call` recurses into so that
    `id`/`type`/`function.name` stay readable instead of being digested along with
    everything else. A message that isn't itself a dict is digested wholesale rather
    than assumed safe: these structures are built internally by this service, but a
    redaction helper's wrong guess costs a leaked secret, not a crashed request, so it
    fails closed instead of trusting the shape.

    Returns a new structure; the caller's messages are not mutated.
    """
    masked = []

    for message in messages:
        if not isinstance(message, dict):
            masked.append(redact_value(message))
            continue

        new_message = {}

        for key, value in message.items():
            if key in _MESSAGE_PASSTHROUGH_KEYS:
                new_message[key] = value
            elif key == _TOOL_CALL_KEY and isinstance(value, list):
                new_message[key] = [_redact_tool_call(tool_call) for tool_call in value]
            else:
                new_message[key] = redact_value(value)

        masked.append(new_message)

    return masked


def _redact_tool_call(tool_call: Any) -> dict | str:
    """Mask a tool_calls entry.

    `id`/`type` and `function.name` pass through, the rest is digested — same
    fail-closed stance as `redact_messages`.
    """
    if not isinstance(tool_call, dict):
        return redact_value(tool_call)
    function = tool_call.get(_FUNCTION_KEY)
    if not isinstance(function, dict):
        return redact_value(tool_call)
    new_function = {
        key: value if key in _FUNCTION_PASSTHROUGH_KEYS else redact_value(value)
        for key, value in function.items()
    }

    result = deepcopy(tool_call)
    for key, value in result.items():
        if key not in _TOOL_CALL_STRUCTURAL_KEYS:
            result[key] = redact_value(value)
    result[_FUNCTION_KEY] = new_function
    return result


def redacted_dump(model) -> dict:
    """model_dump() a pydantic model then redact (AgentRequest, LLMData, etc.)."""
    return redact(model.model_dump())
