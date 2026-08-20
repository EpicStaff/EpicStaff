"""Logging helpers — redact secrets before dumping request/config/messages to logs."""

from __future__ import annotations

_SENSITIVE = {
    "api_key",
    "auth",
    "authorization",
    "headers",
    "extra_headers",
    "password",
    "token",
    "secret",
}


def redact(value):
    """Recursively mask sensitive keys in dicts/lists; returns a new structure."""
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE and v is not None else redact(v))
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]

    return value


def redacted_dump(model) -> dict:
    """model_dump() a pydantic model then redact (AgentRequest, LLMData, etc.)."""
    return redact(model.model_dump())
