import contextlib
import copy
import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

from core import config
from loguru import logger
from uvicorn.config import LOGGING_CONFIG

# Query parameters that carry credentials: the browser sends the user's JWT as `token` on
# `/realtime/`, and Twilio media streams carry a `stream_token`.
SENSITIVE_QUERY_PARAMETERS = ("token", "stream_token")
REDACTED_VALUE = "[REDACTED]"

_SENSITIVE_QUERY_VALUE = re.compile(
    r"([?&](?:" + "|".join(map(re.escape, SENSITIVE_QUERY_PARAMETERS)) + r")=)[^&#\s\"']*",
    re.IGNORECASE,
)

_stderr_handler_id: int | None = None


def configure_logging() -> None:
    """Replace loguru's default handler with a stderr handler that hides variable values.

    `diagnose=False` matters: with loguru's default, `logger.exception` tracebacks print the
    value of every variable on the failing lines, which writes API keys, transcripts and audio
    payloads into the logs. The level is DEBUG in debug mode and INFO otherwise.

    NOTE: several debug log sites print conversation text (transcripts, agent replies), so
    `REALTIME_DEBUG_MODE` must not be enabled on a shared host.

    Idempotent: a second call in the same process is a no-op. Removes only loguru's default
    handler, so sinks added by other code (e.g. test fixtures) survive.
    """
    global _stderr_handler_id
    if _stderr_handler_id is not None:
        return

    # Loguru's default handler has id 0; it is already gone if other code removed it.
    with contextlib.suppress(ValueError):
        logger.remove(0)

    _stderr_handler_id = logger.add(
        sys.stderr,
        level="DEBUG" if config.REALTIME_DEBUG_MODE else "INFO",
        diagnose=False,
        backtrace=False,
    )


def redact_sensitive_query_parameters(text: str) -> str:
    """Replace the values of `SENSITIVE_QUERY_PARAMETERS` in any URL query string in `text`."""
    return _SENSITIVE_QUERY_VALUE.sub(r"\1" + REDACTED_VALUE, text)


class SensitiveQueryParameterFilter(logging.Filter):
    """Redact credential query parameters from uvicorn log records before they are formatted.

    Uvicorn logs the WebSocket handshake path with its query string, in `record.args` for
    its own messages and in `record.msg` when a caller passes a pre-formatted string.
    `record.args` is a mapping when the caller used `%(name)s` placeholders.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_query_parameters(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_if_string(argument) for argument in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {key: _redact_if_string(value) for key, value in record.args.items()}
        return True


def _redact_if_string(value: Any) -> Any:
    return redact_sensitive_query_parameters(value) if isinstance(value, str) else value


def build_uvicorn_log_config() -> dict[str, Any]:
    """Return uvicorn's default logging config with credential redaction on every handler.

    Pass the result as `uvicorn.run(log_config=...)`: uvicorn applies it in the main process
    and again in each worker and reload subprocess.
    """
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["filters"] = {
        "redact_sensitive_query_parameters": {"()": SensitiveQueryParameterFilter}
    }
    # On the handlers, not the loggers: a logger's filters skip records propagated from its
    # children (`uvicorn.error` has no handler of its own and propagates to `uvicorn`).
    for handler in log_config["handlers"].values():
        handler["filters"] = ["redact_sensitive_query_parameters"]
    return log_config
