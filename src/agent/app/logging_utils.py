"""Logging helpers — redact secrets before dumping request/config/messages/errors to logs."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from copy import deepcopy
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

import httpx2
from loguru import logger
from pydantic import ValidationError

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


# Scheme, then userinfo up to the authority's last "@" (any character but whitespace,
# "/", "?" or "#"), then the host and port, then the rest of the URL up to whitespace, a
# double quote or an angle bracket. A single quote does not end the rest, since a path
# can hold one; a closing single quote right after a URL is dropped with it.
# No word boundary in front: "xhttps://…" must be cut too.
_URL = re.compile(r"(?i)(https?://)(?:[^\s/?#]*@)?([^\s/?#'\"<>@]*)[^\s\"<>]*")

# The mcp SDK logs under its module names, except ClientSession, which logs as "client".
_MCP_SDK_LOGGER_NAMES = ("mcp", "client")


def url_origin(url: str | httpx2.URL) -> str:
    """Render a URL held as a value as its origin, `scheme://host[:port]`.

    Parsed rather than matched, so no character in the userinfo or path can hide them:
    each can carry a credential (a password, an API key in the path as some providers
    issue them), as can the query and fragment.
    """
    parts = urlsplit(str(url))
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def redact_urls(text: str) -> str:
    """Cut every http(s) URL in free `text` down to its origin, `scheme://host[:port]`.

    For the URLs a library quotes in its own messages, where they cannot be parsed out
    as values; a URL held as a value goes through `url_origin` instead.
    """
    return _URL.sub(r"\1\2", text)


def http_status_text(code: int) -> str:
    """Name an HTTP status as "HTTP 401 Unauthorized", with the standard reason phrase
    for the code rather than the server's own text."""
    try:
        return f"HTTP {code} {HTTPStatus(code).phrase}"
    except ValueError:
        return f"HTTP {code}"


def describe_http_status_error(error: httpx2.HTTPStatusError) -> str:
    """Render a status error as "HTTP 401 Unauthorized from <origin>".

    httpx2's own text quotes the full request URL, any redirect Location and the
    server's reason phrase.
    """
    origin = url_origin(error.request.url)
    return f"{http_status_text(error.response.status_code)} from {origin}"


class _RedactingSdkLogHandler(logging.Handler):
    """Hand the mcp SDK's stdlib log records to loguru, without URL secrets or payloads.

    The SDK quotes request URLs in its own messages (an unfollowed redirect's target),
    and the exceptions it logs quote them too (an httpx2 status error on the SSE message
    endpoint, which is joined onto the configured URL) or quote the server's payload (a
    pydantic error's input_value). So the message has its URLs cut, a status error is
    named by its status and origin, any other exception becomes its class name and a
    digest, and no traceback is forwarded.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = redact_urls(record.getMessage())
            if record.exc_info and record.exc_info[1] is not None:
                text = f"{text}: {_describe_sdk_exception(record.exc_info[1])}"
            try:
                level: str | int = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            _attributed_to(record).log(level, text)
        except Exception:
            # Never handleError: it prints the raw record to stderr.
            _attributed_to(record).error("unrenderable {} log record", record.name)


def _attributed_to(record: logging.LogRecord):
    def _patch(loguru_record: dict) -> None:
        loguru_record.update(name=record.name, function=record.funcName, line=record.lineno)

    return logger.patch(_patch)


def _describe_sdk_exception(error: BaseException) -> str:
    # The SDK's task groups wrap a single failure in an exception group.
    while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    if isinstance(error, httpx2.HTTPStatusError):
        return describe_http_status_error(error)
    return format_exception_for_log(error)


def route_mcp_sdk_logs_to_loguru() -> None:
    """Send the mcp SDK's log records through `_RedactingSdkLogHandler` only. Idempotent.

    Without it the agent, which configures no stdlib handler, prints them to stderr
    through `logging.lastResort`, verbatim and with tracebacks. A handler rather than a
    filter, because a logger's filters skip records created on its child loggers. The
    WARNING floor keeps the SDK's DEBUG lines, which carry tool arguments and results,
    from being created at all, whatever the root logger's level.
    """
    for name in _MCP_SDK_LOGGER_NAMES:
        sdk_logger = logging.getLogger(name)
        if not any(isinstance(handler, _RedactingSdkLogHandler) for handler in sdk_logger.handlers):
            sdk_logger.addHandler(_RedactingSdkLogHandler())
        sdk_logger.setLevel(logging.WARNING)
        sdk_logger.propagate = False


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


def summarize_validation_error(error: ValidationError) -> str:
    """Summarize a pydantic `ValidationError` as types and locations only.

    Pydantic's own rendering error can contains sensitive data. This
    reads exactly two keys per entry — `type` and `loc` — and never touches `msg`,
    `input`, `ctx` or `url`.

    Known limitation, accepted: for a `dict[str, X]` field the `loc` tuple contains the
    dict *key*, so a secret's name (not its value) can reach the log.

    Fails closed: any problem reading the entries yields the class name alone.
    """
    try:
        failures = [
            f"{entry['type']} at {_format_location(entry['loc'])}" for entry in error.errors()
        ]
        return f"{type(error).__name__}: {len(failures)} error(s) [{'; '.join(failures)}]"
    except Exception:
        return type(error).__name__


def _format_location(location: tuple) -> str:
    return ".".join(str(part) for part in location) or "<root>"


def format_exception_for_log(error: BaseException) -> str:
    """Render an exception as its class name plus a digest of its message.

    Replaces `logger.exception` / `str(error)` at sites that handle untrusted or
    secret-bearing data: a traceback repeats the arguments of every frame on the stack,
    and an exception message routinely quotes the value that caused it. The class name
    says what went wrong; the digest lets two log lines be compared for equal content
    without revealing it.

    Fails closed: if the exception's `__str__` raises, the class name alone is returned.
    """
    try:
        return f"{type(error).__name__}: {redact_value(str(error))}"
    except Exception:
        return type(error).__name__


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


def redact_payload(payload: Any, *, passthrough: set[str]) -> dict | str:
    """Redact a dict for logging: digest every field by default.

    Only keys in the `passthrough` set pass through unchanged; all other keys have
    their values replaced by a `redact_value` digest. Fails closed: unrecognized keys
    are masked, not trusted.

    Returns a new dict; the caller's payload is not mutated.
    """
    if not isinstance(payload, dict):
        return redact_value(payload)

    return {
        key: value if key in passthrough else redact_value(value) for key, value in payload.items()
    }
