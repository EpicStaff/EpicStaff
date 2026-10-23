import atexit
import importlib
import logging
import logging.handlers
import sys

import pytest
import settings
from bootstrap.logging_setup import build_litestar_logging_config, configure_logging
from litestar.logging.config import default_handlers
from loguru import logger


@pytest.fixture
def restored_loguru_default_sink():
    """Put back loguru's default DEBUG stderr sink, which configure_logging() removes."""
    yield
    logger.remove()
    logger.add(sys.stderr)


def _stop_queue_listener(handler) -> None:
    """Stop `handler`'s QueueListener if it's still running, draining its queue first.

    Idempotent: a test may stop the listener itself (see `_stop_root_queue_listener`)
    before the fixture teardown below also tries to stop it. `QueueListener.stop()`
    has no re-entry guard in this Python version, so calling it twice raises
    `AttributeError` on the already-cleared thread — checking `_thread is not None`
    avoids that.
    """
    listener = getattr(handler, "listener", None)
    if listener is not None and listener._thread is not None:
        listener.stop()
        # Litestar registers listener.stop with atexit; a second stop at
        # interpreter exit would hit the same re-entry issue.
        atexit.unregister(listener.stop)


@pytest.fixture
def restored_stdlib_logging():
    """Restore the root logger after the test, stopping any QueueListener it started."""
    root_logger = logging.getLogger()
    saved_handlers, saved_level = list(root_logger.handlers), root_logger.level

    yield

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        _stop_queue_listener(handler)
        handler.close()
    root_logger.handlers = saved_handlers
    root_logger.setLevel(saved_level)


def _stop_root_queue_listener() -> None:
    """Stop the root logger's QueueListener so every record already queued is written.

    Permanently stops the listener thread (no further records will be processed
    after this) — not a reversible flush. `QueueListener.stop()` enqueues a sentinel
    and joins the listener thread, so it only returns once every prior record has
    actually been handled — unlike polling `queue.empty()`, which can read `True`
    the instant a record is dequeued, before the listener has called `handle()` on
    it and written it out.
    """
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            _stop_queue_listener(handler)


def test_configure_logging_drops_records_below_knowledge_log_level(
    restored_loguru_default_sink, capsys, monkeypatch
):
    monkeypatch.setattr(settings, "LOG_LEVEL", "WARNING")
    configure_logging()

    logger.info("info record must be filtered")
    logger.warning("warning record must be written")

    stderr = capsys.readouterr().err
    assert "info record must be filtered" not in stderr
    assert "warning record must be written" in stderr


def build_embedder(api_key: str):
    """Fail the way a provider call does, with the key alive in a traceback frame."""
    raise RuntimeError("provider rejected the key")


def test_configure_logging_keeps_frame_variables_out_of_tracebacks(
    restored_loguru_default_sink, capsys, monkeypatch
):
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging()
    provider_api_key = "sk-logging-setup-provider-key"

    try:
        build_embedder(provider_api_key)
    except RuntimeError:
        logger.exception("embedder construction failed")

    stderr = capsys.readouterr().err
    assert "build_embedder" in stderr
    assert provider_api_key not in stderr


def test_configure_logging_twice_writes_each_record_once(
    restored_loguru_default_sink, capsys, monkeypatch
):
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging()
    configure_logging()

    logger.info("single stderr sink probe")

    assert capsys.readouterr().err.count("single stderr sink probe") == 1


def test_litestar_logging_config_drops_third_party_debug_records(
    restored_stdlib_logging, monkeypatch, capsys
):
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    build_litestar_logging_config().configure()

    # A dedicated name, not "graphrag" itself: logger objects live in the global
    # `logging.Manager` for the rest of the process, so reusing a real third-party
    # logger's name here would leak its DEBUG level into every later test.
    third_party = logging.getLogger("test_third_party_debug_source")
    third_party.setLevel(logging.DEBUG)
    try:
        third_party.debug("SECRET-DOCUMENT-TEXT")
        third_party.info("Workflow completed: extract_graph")

        _stop_root_queue_listener()
        err = capsys.readouterr().err
        assert "SECRET-DOCUMENT-TEXT" not in err
        assert "Workflow completed: extract_graph" in err
    finally:
        third_party.setLevel(logging.NOTSET)


@pytest.mark.parametrize("loguru_level, expected_number", [("TRACE", 5), ("SUCCESS", 25)])
def test_litestar_logging_config_accepts_loguru_only_levels(
    restored_stdlib_logging, monkeypatch, loguru_level, expected_number
):
    monkeypatch.setattr(settings, "LOG_LEVEL", loguru_level)
    config = build_litestar_logging_config()
    for handler in config.handlers.values():
        assert handler["level"] == expected_number
    config.configure()


def test_build_litestar_logging_config_does_not_mutate_global_defaults(
    restored_stdlib_logging, monkeypatch
):
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    build_litestar_logging_config().configure()
    assert default_handlers["console"]["level"] == "DEBUG"


def test_litestar_logging_config_floors_root_level_at_info(
    restored_stdlib_logging, monkeypatch, capsys
):
    """`KNOWLEDGE_LOG_LEVEL=DEBUG` must not raise third-party loggers that rely on
    root's inherited level (e.g. litellm's own loggers, which default to
    `propagate=True` with no level of their own) all the way to DEBUG — that would
    silently reopen the same document-content leak this fix closes for graphrag,
    through a library nobody explicitly asked to be verbose. INFO still passes.
    """
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    build_litestar_logging_config().configure()

    inherited_level_logger = logging.getLogger("test_inherited_level_source")
    try:
        inherited_level_logger.debug("DEBUG-RECORD-MUST-STAY-SUPPRESSED")
        inherited_level_logger.info("INFO-RECORD-MUST-PASS")

        _stop_root_queue_listener()
        err = capsys.readouterr().err
        assert "DEBUG-RECORD-MUST-STAY-SUPPRESSED" not in err
        assert "INFO-RECORD-MUST-PASS" in err
    finally:
        inherited_level_logger.setLevel(logging.NOTSET)


def test_litestar_logging_config_can_still_tighten_root_above_info(
    restored_stdlib_logging, monkeypatch, capsys
):
    """The INFO floor is a floor, not a fixed override — `KNOWLEDGE_LOG_LEVEL` above
    INFO still quiets a logger that relies on root's inherited level.
    """
    monkeypatch.setattr(settings, "LOG_LEVEL", "WARNING")
    build_litestar_logging_config().configure()

    inherited_level_logger = logging.getLogger("test_inherited_level_source_tighten")
    try:
        inherited_level_logger.info("INFO-RECORD-MUST-STAY-SUPPRESSED")
        inherited_level_logger.warning("WARNING-RECORD-MUST-PASS")

        _stop_root_queue_listener()
        err = capsys.readouterr().err
        assert "INFO-RECORD-MUST-STAY-SUPPRESSED" not in err
        assert "WARNING-RECORD-MUST-PASS" in err
    finally:
        inherited_level_logger.setLevel(logging.NOTSET)


def test_main_wires_build_litestar_logging_config_into_the_app(
    restored_loguru_default_sink, restored_stdlib_logging
):
    """Pins main.py's own `Litestar(..., logging_config=...)` call site."""
    sys.modules.pop("main", None)
    try:
        main_module = importlib.import_module("main")
        queue_listener_level = main_module.app.logging_config.handlers["queue_listener"]["level"]
        assert queue_listener_level == logger.level(settings.LOG_LEVEL).no
    finally:
        sys.modules.pop("main", None)
