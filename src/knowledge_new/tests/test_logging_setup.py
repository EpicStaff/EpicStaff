import sys

import pytest
import settings
from bootstrap.logging_setup import configure_logging
from loguru import logger


@pytest.fixture
def restored_loguru_default_sink():
    """Put back loguru's default DEBUG stderr sink, which configure_logging() removes."""
    yield
    logger.remove()
    logger.add(sys.stderr)


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
