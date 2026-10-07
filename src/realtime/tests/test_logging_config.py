import copy
import logging
import logging.config
import sys

import pytest
from core import config, logging_config
from core.logging_config import (
    SensitiveQueryParameterFilter,
    build_uvicorn_log_config,
    configure_logging,
)
from loguru import logger
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter

SECRET_API_KEY = "sk-test-secret-123"
USER_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjo3fQ.c2lnbmF0dXJl"
UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture
def unconfigured_logging():
    """Start from a process where configure_logging() has not run yet.

    `api.main` configures logging at import, so another test module may already have done it.
    """
    previous_handler_id = logging_config._stderr_handler_id
    removed_loguru_default_handler = False
    if previous_handler_id is not None:
        logger.remove(previous_handler_id)
    else:
        try:
            logger.remove(0)
            removed_loguru_default_handler = True
        except ValueError:
            pass
    logging_config._stderr_handler_id = None
    yield
    if logging_config._stderr_handler_id is not None:
        logger.remove(logging_config._stderr_handler_id)
    logging_config._stderr_handler_id = None
    if previous_handler_id is not None:
        configure_logging()
    elif removed_loguru_default_handler:
        # Loguru's default handler is a DEBUG stderr sink with default options.
        logger.add(sys.stderr)


@pytest.fixture
def restored_uvicorn_loggers():
    """Undo the global stdlib logging changes a dictConfig() call makes to uvicorn's loggers."""
    saved_state = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in UVICORN_LOGGER_NAMES
    }
    yield
    for name, (handlers, level, propagate) in saved_state.items():
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers = handlers
        stdlib_logger.setLevel(level)
        stdlib_logger.propagate = propagate


def _connect_with_secret_key():
    api_key = SECRET_API_KEY
    raise ValueError(f"provider rejected a key of length {len(api_key)}")


def _uvicorn_record(name: str, message: str, args: tuple) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, args, None)


def test_logged_exception_does_not_leak_local_variable_values(unconfigured_logging, capsys):
    configure_logging()

    try:
        _connect_with_secret_key()
    except ValueError:
        logger.exception("Realtime connection failed")

    stderr = capsys.readouterr().err
    assert "Realtime connection failed" in stderr
    assert "ValueError: provider rejected a key of length 18" in stderr
    assert SECRET_API_KEY not in stderr


def test_configure_logging_twice_writes_each_record_once(unconfigured_logging, capsys):
    configure_logging()
    configure_logging()

    logger.info("single stderr handler probe")

    stderr = capsys.readouterr().err
    assert stderr.count("single stderr handler probe") == 1


def test_configure_logging_keeps_info_level_outside_debug_mode(
    unconfigured_logging, capsys, monkeypatch
):
    monkeypatch.setattr(config, "REALTIME_DEBUG_MODE", False)
    configure_logging()

    logger.debug("debug record must be filtered")
    logger.info("info record must be written")

    stderr = capsys.readouterr().err
    assert "debug record must be filtered" not in stderr
    assert "info record must be written" in stderr


def test_configure_logging_writes_debug_records_in_debug_mode_without_variable_values(
    unconfigured_logging, capsys, monkeypatch
):
    monkeypatch.setattr(config, "REALTIME_DEBUG_MODE", True)
    configure_logging()

    logger.debug("debug record must be written")
    try:
        _connect_with_secret_key()
    except ValueError:
        logger.exception("Realtime connection failed")

    stderr = capsys.readouterr().err
    assert "debug record must be written" in stderr
    assert "ValueError: provider rejected a key of length 18" in stderr
    assert SECRET_API_KEY not in stderr


def test_configure_logging_keeps_sinks_added_by_other_code(
    unconfigured_logging, captured_log_messages
):
    configure_logging()

    logger.info("record for an existing sink")

    assert any("record for an existing sink" in message for message in captured_log_messages)


def test_filter_redacts_token_in_accepted_websocket_handshake_record():
    record = _uvicorn_record(
        "uvicorn.error",
        '%s - "WebSocket %s" [accepted]',
        ("172.18.0.9:51234", f"/realtime/?connection_key=abc-123&token={USER_JWT}"),
    )

    assert SensitiveQueryParameterFilter().filter(record) is True

    message = record.getMessage()
    assert USER_JWT not in message
    assert (
        message
        == '172.18.0.9:51234 - "WebSocket /realtime/?connection_key=abc-123&token=[REDACTED]"'
        " [accepted]"
    )


def test_filter_redacts_token_in_rejected_websocket_handshake_record():
    record = _uvicorn_record(
        "uvicorn.error",
        '%s - "WebSocket %s" 403',
        ("172.18.0.9:51234", f"/realtime/?token={USER_JWT}&connection_key=abc-123"),
    )

    SensitiveQueryParameterFilter().filter(record)

    assert (
        record.getMessage()
        == '172.18.0.9:51234 - "WebSocket /realtime/?token=[REDACTED]&connection_key=abc-123" 403'
    )


def test_filter_redacts_stream_token_and_keeps_similarly_named_parameters():
    record = _uvicorn_record(
        "uvicorn.error",
        '%s - "WebSocket %s" [accepted]',
        ("10.0.0.1:4000", "/voice/7/stream?stream_token=st-secret&not_a_token=kept"),
    )

    SensitiveQueryParameterFilter().filter(record)

    message = record.getMessage()
    assert "st-secret" not in message
    assert "stream_token=[REDACTED]" in message
    assert "not_a_token=kept" in message


def test_filter_redacts_token_in_mapping_args_record():
    # LogRecord unwraps a single mapping argument into `record.args`.
    record = _uvicorn_record(
        "uvicorn.error",
        '%(client)s - "WebSocket %(path)s" %(status)d',
        ({"client": "172.18.0.9:51234", "path": f"/realtime/?token={USER_JWT}", "status": 403},),
    )
    assert isinstance(record.args, dict)

    assert SensitiveQueryParameterFilter().filter(record) is True

    assert record.getMessage() == '172.18.0.9:51234 - "WebSocket /realtime/?token=[REDACTED]" 403'


def test_filter_redacts_sensitive_parameter_names_case_insensitively():
    record = _uvicorn_record(
        "uvicorn.error",
        '%s - "WebSocket %s" [accepted]',
        ("10.0.0.1:4000", f"/realtime/?Token={USER_JWT}&STREAM_TOKEN=st-secret"),
    )

    SensitiveQueryParameterFilter().filter(record)

    message = record.getMessage()
    assert USER_JWT not in message
    assert "st-secret" not in message
    assert "?Token=[REDACTED]&STREAM_TOKEN=[REDACTED]" in message


def test_filter_redacts_token_in_preformatted_message():
    record = _uvicorn_record(
        "uvicorn.error", f'"WebSocket /realtime/?connection_key=abc-123&token={USER_JWT}" 403', ()
    )

    SensitiveQueryParameterFilter().filter(record)

    assert record.getMessage() == '"WebSocket /realtime/?connection_key=abc-123&token=[REDACTED]" 403'


def test_filter_redacts_token_in_access_log_record_formatted_by_uvicorn():
    record = _uvicorn_record(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("172.18.0.9:51234", "GET", f"/realtime/?connection_key=abc-123&token={USER_JWT}", "1.1", 200),
    )

    SensitiveQueryParameterFilter().filter(record)
    formatted = AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s').format(
        record
    )

    assert USER_JWT not in formatted
    assert "/realtime/?connection_key=abc-123&token=[REDACTED] HTTP/1.1" in formatted


def test_uvicorn_log_config_does_not_mutate_uvicorn_default_config():
    uvicorn_default_before = copy.deepcopy(LOGGING_CONFIG)

    build_uvicorn_log_config()

    assert LOGGING_CONFIG == uvicorn_default_before


def test_uvicorn_log_config_redacts_tokens_in_error_and_access_output(
    restored_uvicorn_loggers, capsys
):
    logging.config.dictConfig(build_uvicorn_log_config())

    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]',
        "172.18.0.9:51234",
        f"/realtime/?connection_key=abc-123&token={USER_JWT}",
    )
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "172.18.0.9:51234",
        "GET",
        f"/voice/7/stream?stream_token={USER_JWT}",
        "1.1",
        101,
    )

    captured = capsys.readouterr()
    assert USER_JWT not in captured.err
    assert USER_JWT not in captured.out
    assert "connection_key=abc-123&token=[REDACTED]" in captured.err
    assert "stream_token=[REDACTED]" in captured.out
