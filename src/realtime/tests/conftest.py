import re

import pytest
from core import config
from foundation.cryptographer import FernetRotatedCryptographer
from loguru import logger

# Shared fixtures (sample chat data, tool manager) available to every test module.
pytest_plugins = ["tests.fixtures"]

CONNECTION_KEY = "mock_key"
TOKEN = "mock_token"
CONNECTION_URL = f"/realtime/?connection_key={CONNECTION_KEY}&token={TOKEN}"

SECRET_SENTINEL = "sk-live-SENTINEL-do-not-leak-4316"
PUBLIC_ERROR_REFERENCE = re.compile(r"\(reference: ([0-9a-f]{12})\)")

TRANSPORT_KEY = "realtime-test-transport-key-0001"
OTHER_TRANSPORT_KEY = "another-deployments-transport-key"
# Spelled out rather than read from config, so a drift in realtime's configured value fails the tests.
DJANGO_TRANSPORT_HKDF_INFO = b"epicstaff.secrets.transport.v1"

# What the realtime composition root builds from its settings, under the test key.
TRANSPORT_CRYPTOGRAPHER = FernetRotatedCryptographer(
    TRANSPORT_KEY, hkdf_info=config.SECRETS_TRANSPORT_HKDF_INFO.encode()
)


def seal(plaintext: str, key: str = TRANSPORT_KEY) -> str:
    """Encrypt the way django_app seals a secret it sends to realtime."""
    return FernetRotatedCryptographer(key, hkdf_info=DJANGO_TRANSPORT_HKDF_INFO).encrypt(plaintext)


@pytest.fixture
def app_transport_cryptographer(monkeypatch):
    """Make the `api.main` routes decrypt under the test transport key instead of the configured one."""
    monkeypatch.setattr("api.main.transport_cryptographer", TRANSPORT_CRYPTOGRAPHER)


@pytest.fixture
def captured_log_messages():
    """Collect every formatted loguru message (tracebacks included) emitted during a test."""
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    yield messages
    logger.remove(sink_id)
