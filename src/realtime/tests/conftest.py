import re

import pytest
from foundation.utils.error_reference import REFERENCE_PATTERN
from loguru import logger

# Shared fixtures (sample chat data, tool manager) available to every test module.
pytest_plugins = ["tests.fixtures"]

CONNECTION_KEY = "mock_key"
TOKEN = "mock_token"
CONNECTION_URL = f"/realtime/?connection_key={CONNECTION_KEY}&token={TOKEN}"

SECRET_SENTINEL = "sk-live-SENTINEL-do-not-leak-4316"
PUBLIC_ERROR_REFERENCE = re.compile(rf"\(reference: ({REFERENCE_PATTERN})\)")


@pytest.fixture
def captured_log_messages():
    """Collect every formatted loguru message (tracebacks included) emitted during a test."""
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    yield messages
    logger.remove(sink_id)
