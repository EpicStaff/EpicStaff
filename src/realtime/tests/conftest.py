import re

import pytest
from loguru import logger

CONNECTION_KEY = "mock_key"
TOKEN = "mock_token"
CONNECTION_URL = f"/realtime/?connection_key={CONNECTION_KEY}&token={TOKEN}"

SECRET_SENTINEL = "sk-live-SENTINEL-do-not-leak-4316"
PUBLIC_ERROR_REFERENCE = re.compile(r"\(reference: ([0-9a-f]{12})\)")


@pytest.fixture
def captured_log_messages():
    """Collect every formatted loguru message (tracebacks included) emitted during a test."""
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    yield messages
    logger.remove(sink_id)
